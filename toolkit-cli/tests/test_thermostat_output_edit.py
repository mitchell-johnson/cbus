"""Literal Edit outcomes on the causal output/reference graph."""
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
from test_thermostat_output_add import add, select
from test_thermostat_output_groups import FIELDS, raw_values, seed, materialize
from test_thermostat_remote_references import PATH, oid, node
from test_thermostat_settings import _spec


def edit(parameter='HeatStage1Output', *, outcome='accept', **changes):
    return dict(op='edit-output-group', parameter=parameter, outcome=outcome, **changes)


class OutputEditTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        for family in ('THERMOSTATA', 'THERMOSTATB'):
            (self.folder / (family + '.xml')).write_text(_spec(family, set(raw_values())))
        self.store = UnitSpecStore(self.folder)

    def plan(self, operations=(), *, kind='PC_TSA5', raw=None, apps=None, xml=None, prompts=None):
        raw = raw_values(HeatStage1Output=20) if raw is None else raw
        if xml is None:
            apps = {56: {20: 'Alpha', 21: 'Beta', 255: '<Unused>'},
                    172: {7: 'Zone'}, 203: {}} if apps is None else apps
            root = ET.fromstring(seed(kind, raw, apps))
            root.find('./Project/TagName').text = 'Thermostat Project'
            xml = ET.tostring(root, encoding='unicode')
        return plan_remote_references(self.store, kind, raw, {}, project_xml=xml,
            unit_path=PATH, output_operations=operations, level_prompts=prompts)

    def test_same_identity_name_only_and_all_four_aliases(self):
        for kind in ('PC_TSA', 'PC_TSA5', 'PC_TSB', 'PC_TSB5'):
            with self.subTest(kind=kind):
                p = self.plan([edit(name=' \t Bedroom  heat \r\n')], kind=kind)
                self.assertFalse(p.pp_mutation_required)
                self.assertTrue(p.graph_mutation_required)
                self.assertEqual(p.creations, ())
                self.assertEqual(p.output_expected['HeatStage1Output'], 20)
                self.assertEqual(p.output_requested_parameters, ())
                self.assertEqual([(r.application, r.address, r.identity, r.previous_name, r.name,
                                   r.output_edit, r.reason) for r in p.renames],
                    [(56, 20, oid('group:56:20'), 'Alpha', 'Bedroom  heat', True,
                      'output_edit:1:HeatStage1Output')])
                view = p.as_dict()['output_projection']
                r = view['edit_dialogs'][0]
                self.assertEqual(r['identity'], r['previous_identity'])
                self.assertEqual((r['address'], r['shown_name'], r['entered_name'], r['name']),
                    (20, 'Alpha', ' \t Bedroom  heat \r\n', 'Bedroom  heat'))
                self.assertFalse(r['object_created'])
                self.assertTrue(r['changed'])
                self.assertFalse(view['original_edit_storage_callbacks_reproduced'])
                self.assertFalse(view['original_manager_sort_timers_reproduced'])
                self.assertEqual(p.as_dict()['planned_renames'][0]['output_edit'], True)
                self.assertEqual(validate_remote_plan(self.store, p), p)

    def test_ordered_select_edit_add_and_return_to_original_name(self):
        p = self.plan([edit(name='Temporary'), select('HeatStage1Output', 21),
            edit(name='Alpha'), select('HeatStage1Output', 20), edit(name='Beta'),
            add('HeatStage2Output', name='Temporary'), edit('HeatStage2Output', name='Created edit'),
            select('HeatStage2Output', 255)])
        self.assertEqual([(r.identity, r.previous_name, r.name) for r in p.renames], [
            (oid('group:56:20'), 'Alpha', 'Temporary'), (oid('group:56:21'), 'Beta', 'Alpha'),
            (oid('group:56:20'), 'Temporary', 'Beta'), ('planned-group:56:0', 'Temporary', 'Created edit')])
        self.assertEqual([(r.action, r.address) for r in p.graph_operations],
                         [('rename', 20), ('rename', 21), ('rename', 20), ('create', 0), ('rename', 0)])
        self.assertEqual(p.output_requested_parameters, ('HeatStage1Output', 'HeatStage2Output'))
        self.assertEqual(p.output_expected['HeatStage2Output'], 255)
        view = p.as_dict()['output_projection']
        self.assertEqual([r['position'] for r in view['edit_dialogs']], [1, 3, 5, 7])
        self.assertEqual(view['edit_dialogs'][3]['shown_name'], 'Temporary')
        self.assertEqual(view['loaded_references']['HeatStage1Output']['name'], 'Beta')
        back = self.plan([edit(name='Intermediate'), edit(name='Alpha')])
        self.assertTrue(back.graph_mutation_required)
        self.assertEqual([(r.previous_name, r.name) for r in back.renames],
                         [('Alpha', 'Intermediate'), ('Intermediate', 'Alpha')])
        self.assertEqual(validate_remote_plan(self.store, p), p)

    def test_omitted_preloaded_long_name_and_same_name_acceptance(self):
        for name in ('Alpha', 'A' * 80, '\U0001f321' * 40):
            apps = {56: {20: name, 255: '<Unused>'}, 172: {7: 'Zone'}, 203: {}}
            with self.subTest(name=name):
                p = self.plan([edit()], apps=apps)
                self.assertFalse(p.apply_would_mutate)
                r = p.as_dict()['output_projection']['edit_dialogs'][0]
                self.assertEqual((r['shown_name'], r['entered_name'], r['name']), (name, name, name))
                self.assertFalse(r['operator_name'])
                if name != 'Alpha':
                    with self.assertRaisesRegex(ThermostatTemplateError, '32 UTF-16'):
                        self.plan([edit(name=name)], apps=apps)
        p = self.plan([edit()], apps={56: {20: ' ' + 'A' * 40 + ' ', 255: '<Unused>'},
                                     172: {7: 'Zone'}, 203: {}})
        self.assertEqual(p.renames[0].name, 'A' * 40)
        self.assertFalse(p.pp_mutation_required)

    def test_direct_cancel_does_not_validate_name_or_project_tag(self):
        raw = raw_values(HeatStage1Output=20)
        for name in (' ', 'Thermostat Project', 'A' * 80):
            root = ET.fromstring(seed(raw=raw,
                apps={56: {20: name, 21: name, 255: '<Unused>'}, 172: {7: 'Zone'}, 203: {}}))
            project = root.find('Project')
            project.remove(project.find('TagName'))
            with self.subTest(name=name):
                p = self.plan([edit(outcome='cancel')], raw=raw, xml=ET.tostring(root, encoding='unicode'))
                self.assertFalse(p.apply_would_mutate)
                self.assertIsNone(p.as_dict()['output_projection']['project_tag_name'])
                r = p.as_dict()['output_projection']['edit_dialogs'][0]
                self.assertIsNone(r['entered_name'])
                self.assertEqual((r['name'], r['changed']), (name, False))
                with self.assertRaisesRegex(ThermostatTemplateError, 'Project.TagName'):
                    self.plan([edit()], raw=raw, xml=ET.tostring(root, encoding='unicode'))

    def test_explicit_text_utf16_trim_case_and_transport_domain(self):
        for entered, expected in [(' \t New name \r\n', 'New name'), ('A' * 32, 'A' * 32),
                ('\U0001f321' * 16, '\U0001f321' * 16), ('\u00a0', '\u00a0'),
                ('Quoted "A"  \\ path', 'Quoted "A"  \\ path'), ('\u00a0room\u00a0', '\u00a0room\u00a0')]:
            with self.subTest(entered=entered):
                self.assertEqual(self.plan([edit(name=entered)]).renames[0].name, expected)
        for entered in (' ', '\t\r\n', 'A' * 33, ' ' + 'A' * 32, '\U0001f321' * 16 + ' ',
                        '\ud800', 'A\0B', 'A\nB', 'A\x7fB', 'A\ufffeB'):
            with self.subTest(entered=repr(entered)), self.assertRaises(ThermostatTemplateError):
                self.plan([edit(name=entered)])
        with self.assertRaisesRegex(ThermostatTemplateError, '2204'):
            self.plan([edit(name=' Thermostat Project ')])
        self.assertEqual(self.plan([edit(name='thermostat project')]).renames[0].name, 'thermostat project')

    def test_duplicate_check_excludes_only_selected_identity(self):
        self.assertFalse(self.plan([edit(name='Alpha')]).apply_would_mutate)
        for name in ('Beta', 'bETA', ' Beta '):
            with self.subTest(name=name), self.assertRaisesRegex(ThermostatTemplateError, '2203'):
                self.plan([edit(name=name)])
        apps = {56: {20: 'Alpha', 21: 'ALPHA', 22: 'é', 255: '<Unused>'},
                172: {7: 'Zone'}, 203: {23: 'Other application'}}
        with self.assertRaisesRegex(ThermostatTemplateError, '2203'):
            self.plan([edit()], apps=apps)
        self.assertEqual(self.plan([edit(name='É')], apps=apps).renames[0].name, 'É')
        self.assertEqual(self.plan([edit(name='Other application')], apps=apps).renames[0].name,
                         'Other application')
        with self.assertRaisesRegex(ThermostatTemplateError, '2203'):
            self.plan([edit(name='New'), add('HeatStage2Output', name='new')])

    def test_all_23_roles_and_unused_or_disabled_edit_gates(self):
        raw = raw_values(**dict(zip(FIELDS, range(23))))
        apps = {56: {**{i: 'Old ' + str(i) for i in range(23)}, 255: '<Unused>'},
                172: {7: 'Zone'}, 203: {}}
        p = self.plan([edit(name, name='New ' + str(i)) for i, name in enumerate(FIELDS)], raw=raw, apps=apps)
        self.assertEqual([(r.address, r.name) for r in p.renames], [(i, 'New ' + str(i)) for i in range(23)])
        self.assertFalse(p.pp_mutation_required)
        self.assertEqual(p.output_requested_parameters, ())
        for target in FIELDS:
            with self.subTest(unused=target), self.assertRaisesRegex(ThermostatTemplateError, 'non-unused'):
                self.plan([edit(target, outcome='cancel')], raw=raw_values())
        for kind, target in [('PC_TSA', 'InternalRelay1GroupNumber'), ('PC_TSB', 'InternalRelay1GroupNumber'),
                             ('PC_TSB', 'DamperZone1Output'), ('PC_TSB5', 'DamperZone1Output')]:
            with self.subTest(kind=kind, target=target), self.assertRaisesRegex(ThermostatTemplateError, 'hidden or disabled'):
                self.plan([edit(target, name='New')], kind=kind, raw=raw, apps=apps)
        for fields, target in [({'ControlledZones': 0}, 'InternalRelay1GroupNumber'),
                ({'InternalPlantType': 0}, 'HeatStage1Output'),
                ({'InternalPlantType': 1}, 'CoolStage1Output'),
                ({'InternalPlantZones': 1}, 'DamperZone1Output')]:
            changes = dict(fields, **{target: 20})
            with self.subTest(target=target), self.assertRaisesRegex(ThermostatTemplateError, 'hidden or disabled'):
                self.plan([edit(target, name='New')], raw=raw_values(**changes))

    def test_full_capacity_edit_and_cancel_do_not_require_free_address(self):
        apps = {56: {i: 'Old ' + str(i) for i in range(256)}, 172: {7: 'Zone'}, 203: {}}
        p = self.plan([edit(outcome='cancel'), edit(name='Changed')], apps=apps)
        self.assertEqual(p.creations, ())
        self.assertEqual([(r.address, r.previous_name, r.name) for r in p.renames], [(20, 'Old 20', 'Changed')])
        self.assertFalse(p.pp_mutation_required)

    def test_shared_output_remote_and_level_views_preserve_identity(self):
        raw = raw_values(ApplicationNumber=203, RemoteSetbackControlSource=2,
            RemoteSetbackOnGroup=20, RemoteSetbackOffGroup=21, HeatStage1Output=20,
            CoolStage1Output=20, InternalRelay1GroupNumber=20)
        apps = {203: {20: 'Shared', 21: 'Off', 255: '<Unused>'}, 172: {7: 'Zone'}}
        p = self.plan([edit(name='Shared edit'), edit('CoolStage1Output', name='Final shared')],
            raw=raw, apps=apps, prompts={'setback': 'accept'})
        refs = p.as_dict()['output_projection']['resolved_references']
        for name in ('HeatStage1Output', 'CoolStage1Output', 'InternalRelay1GroupNumber'):
            self.assertEqual((refs[name]['identity'], refs[name]['name']), (oid('group:203:20'), 'Final shared'))
        self.assertEqual(p.as_dict()['resolved_roles']['setback_on']['identity'], oid('group:203:20'))
        # Each retained fixture group already owns Address7/Value17; only the
        # other30 required addresses are created, regardless of its name.
        self.assertEqual([(r.group, r.address) for r in p.level_creations],
            [(group, address) for group in (20, 21) for address in range(1, 32) if address != 7])
        self.assertEqual(p.output_requested_parameters, ())
        self.assertEqual(validate_remote_plan(self.store, p), p)

    def test_strict_records_and_legacy_rename_metadata(self):
        invalid = [edit(address=20), edit(extra=1), edit(outcome=True), edit(outcome='ok'),
            edit(outcome='cancel', name='Changed'), edit(parameter=[]), edit(name=None),
            edit(name=True), edit(name=3), {'op': 'edit-output-group'}, edit(outcome=None)]
        for row in invalid:
            with self.subTest(row=row), self.assertRaises(ThermostatTemplateError):
                self.plan([row])
        old = self.plan([], apps={56: {20: '[CG07] Old', 255: '<Unused>'}, 172: {7: 'Zone'}, 203: {}})
        self.assertEqual(len(old.renames), 1)
        self.assertFalse(old.renames[0].output_edit)
        self.assertNotIn('output_edit', old.renames[0].as_dict())
        self.assertNotIn('edit_dialogs', old.as_dict()['output_projection'])
        p = self.plan([edit(name='Explicit')], apps={56: {20: '[CG07] Old', 255: '<Unused>'},
                                                      172: {7: 'Zone'}, 203: {}})
        self.assertEqual([(r.previous_name, r.name, r.output_edit) for r in p.renames],
            [('[CG07] Old', '[CG07] Y (heat/cool)', False), ('[CG07] Y (heat/cool)', 'Explicit', True)])

    def test_replay_binds_edit_input_receipts_and_strict_provenance(self):
        p = self.plan([edit(name='Changed')])
        view = p.as_dict()['output_projection']
        bad_view = dict(view, edit_dialogs=[dict(view['edit_dialogs'][0], previous_name='Other')])
        bad_rename = replace(p.renames[0], previous_name='Wrong')
        for changed in (replace(p, output_projection_json=json.dumps(bad_view)),
                replace(p, output_operations=(json.dumps(edit(name='Other')),)),
                replace(p, graph_operations=(bad_rename,)),
                replace(p, output_values=(('HeatStage1Output', 21),)),
                replace(p, project_xml=p.project_xml.replace('Alpha', 'Changed before plan'))):
            with self.subTest(changed=repr(changed.output_operations)), self.assertRaises(ThermostatTemplateError):
                validate_remote_plan(self.store, changed)
        for flag in (False, 0, 1, 'true', None):
            changed = replace(p, graph_operations=(replace(p.renames[0], output_edit=flag),))
            with self.subTest(flag=flag), self.assertRaises(ThermostatTemplateError):
                validate_remote_plan(self.store, changed)

    def test_full_preservation_retains_opaque_metadata_and_checks_rename_chain(self):
        p = self.plan([edit(name='First'), edit(name='Second')])
        root, receipts = materialize(p)
        after = ET.tostring(root, encoding='unicode')
        def verify(text, operations=p.graph_operations):
            return verify_project_preservation(p.project_xml, text, PATH, changed_parameters=p.expected,
                created_oids=receipts, graph_operations=operations)
        self.assertTrue(verify(after)['preserved'])
        for mutation in ('name', 'oid', 'level', 'opaque', 'tag-attribute', 'unplanned-group'):
            altered = ET.fromstring(after)
            app = altered.find("./Project/Network/Application[Address='56']")
            group = app.find("Group[Address='20']")
            if mutation == 'name': group.find('TagName').text = 'Unexpected'
            elif mutation == 'oid': group.find('OID').text = oid('wrong')
            elif mutation == 'level': group.find('Level').set('Value', '199')
            elif mutation == 'opaque': group.set('Opaque', 'Changed')
            elif mutation == 'tag-attribute': group.find('TagName').set('Opaque', 'Changed')
            else: node(app, 'Group', 99, 'Unexpected', oid('extra'))
            with self.subTest(mutation=mutation), self.assertRaises(ThermostatTemplateError):
                verify(ET.tostring(altered, encoding='unicode'))
        for row in (replace(p.renames[1], previous_name='Alpha'),
                    replace(p.renames[1], identity=oid('wrong')), replace(p.renames[1], output_edit=1)):
            with self.subTest(row=row), self.assertRaises(ThermostatTemplateError):
                verify(after, (p.renames[0], row))

    @unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE') and os.environ.get('CBUS_TOOLKIT_MAP'),
                         'Explicit original EXE/MAP required for static source verification')
    def test_optional_static_source(self):
        research = Path(__file__).parents[1] / 'research'
        sys.path.insert(0, str(research))
        self.addCleanup(sys.path.remove, str(research))
        from thermostat_output_edit_static import inspect
        actual = inspect(Path(os.environ['CBUS_TOOLKIT_EXE']), Path(os.environ['CBUS_TOOLKIT_MAP']))
        expected = json.loads((research / 'fixtures/thermostat-output-edit-source-review.json').read_text())
        self.assertEqual(actual, expected)


if __name__ == '__main__':
    unittest.main()
