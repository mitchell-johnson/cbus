"""Replayed thermostat Load Template post-load pipeline against owned C-Gate.

Hand-derived expectations for representative installations come from the
recovered UpdateParametersForPlantType/UpdateFanSpeedsForPlantType/BeforeSave
routines (docs/thermostat-templates.md), not from the module tables.
Requires CBUS_CGATE_JAVA, CBUS_LOCAL_CGATE_VENDOR and CBUS_UNITSPEC_DIR.
"""
import json
import io
import os
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import socket
import unittest
from uuid import uuid4
import xml.etree.ElementTree as ET

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit import cli
from cbus_toolkit.native import NativeDatabase, NativeProjects
from cbus_toolkit.programming import Programmer, xml_text
from cbus_toolkit.thermostat_templates import (NativeThermostatTemplates, ThermostatTemplateCatalog,
                                               ThermostatTemplateError)

SPEC_DIR = os.environ.get('CBUS_UNITSPEC_DIR')
# (unit type, catalogue number, family, admitted installations)
CASES = (('PC_TSA', '5070THP,BK', 'programmable', (1, 2, 3, 4, 5, 6, 7, 8)),
         ('PC_TSB', '5070THB,BK', 'basic', (1, 4, 5, 6, 8)))
UNRELATED = {'BacklightActiveTime': 7, 'SetbackLevel': 3, 'TemperatureOffset': 2}
# Independent expectations: parameter values and created [CG01] group tags.
HAND = {
    ('programmable', 1): ({'CoolActivationOutput': 2, 'CoolStage1Output': 1, 'HeatStage1Output': 1,
                           'InternalRelay2GroupNumber': 2, 'InternalRelay4GroupNumber': 4,
                           'EvapProgramEnabled': 0, 'InstallationCode': 1},
                          {1: '[CG01] Y (heat/cool)', 2: '[CG01] B (cool activation)', 3: '[CG01] G (fan)',
                           4: '[CG01] B (heat activation)', 255: '<Unused>'}),
    ('programmable', 5): ({'HeatActivationOutput': 255, 'CoolStage1Output': 1, 'CoolStage3Output': 2,
                           'HeatingPlantFanSpeedControlEnable': 1, 'HeatingPlantFanSpeeds': 2,
                           'HeatingPlantFanEnable': 0, 'NonEvapProgramEnabled': 0, 'EvapProgramEnabled': 0},
                          {1: '[CG01] pump', 2: '[CG01] fill', 3: '[CG01] cool fan speed 1',
                           4: '[CG01] cool fan speed 2', 255: '<Unused>'}),
    ('programmable', 6): ({'InternalPlantType': 8, 'CoolStage2Output': 2, 'CoolStage3Output': 5,
                           'InternalRelay5GroupNumber': 5, 'HeatingPlantFanSpeeds': 2},
                          {1: '[CG01] Y (cool)', 2: '[CG01] Open', 5: '[CG01] Close',
                           3: '[CG01] G1 (fan speed 1)', 4: '[CG01] G2 (fan speed 2)', 255: '<Unused>'}),
    ('basic', 8): ({'CoolStage1Output': 5, 'HeatStage1Output': 6, 'InternalRelay1GroupNumber': 5,
                    'InternalRelay5GroupNumber': 6, 'DamperZone1Output': 255, 'InstallationCode': 8},
                   {5: '[CG01] Y (cool)', 3: '[CG01] G (fan)', 6: '[CG01] W (heat)', 255: '<Unused>'}),
}


def groups(database, network, application):
    root = ET.fromstring(xml_text(database.get(network + '/' + str(application), xml=True)))
    return {int(g.findtext('Address')): g.findtext('TagName') for g in root.findall('Group')}


@unittest.skipUnless(os.environ.get('CBUS_CGATE_JAVA') and os.environ.get('CBUS_LOCAL_CGATE_VENDOR')
                     and SPEC_DIR, 'Select Java11/vendor/unit specifications for native thermostat post-load')
class NativeThermostatPostLoadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from research.local_cgate import LocalCGate
        cls.service = LocalCGate(os.environ['CBUS_LOCAL_CGATE_VENDOR'])
        cls.sentinel = socket.socket()
        cls.addClassCleanup(cls.sentinel.close)
        cls.addClassCleanup(cls.finish)
        cls.addClassCleanup(cls.service.close)
        cls.sentinel.bind(('127.0.0.1', 0))
        cls.sentinel.listen(1)
        cls.sentinel.settimeout(0.05)
        (cls.service.work / 'config/access.txt').write_text('interface 127.0.0.1 Clipsal\n')
        cls.evidence = {}
        cls.service.start()
        cls.evidence = {'format': 'native-thermostat-post-load-integration-v1',
                        'service': cls.service.report, 'cases': [], 'physical_devices_accessed': False}

    @classmethod
    def finish(cls):
        try:
            connection, peer = cls.sentinel.accept()
        except socket.timeout:
            cls.evidence['cni_connections'] = []
        else:
            connection.close()
            raise AssertionError('Closed template workflow connected to its CNI sentinel: ' + repr(peer))
        destination = os.environ.get('CBUS_THERMOSTAT_POST_LOAD_EVIDENCE')
        if destination:
            with Path(destination).open('x', encoding='utf-8') as stream:
                json.dump(cls.evidence, stream, indent=2, default=str)
                stream.write('\n')

    def setUp(self):
        self.client = CGateClient('127.0.0.1', self.service.port, timeout=30)
        self.addCleanup(self.client.close)
        self.client.connect()
        self.projects, self.database = NativeProjects(self.client), NativeDatabase(self.client)
        self.project = 'T' + uuid4().hex[:7].upper()
        self.projects.operation('new', self.project)
        self.network = '//' + self.project + '/254'
        self.database.create_network(self.project, 254, 'OwnedOffline', 'Cni',
                                     '127.0.0.1:' + str(self.sentinel.getsockname()[1]))
        self.catalog = ThermostatTemplateCatalog(SPEC_DIR)

    def reload(self):
        for action in ('save', 'close', 'load'):
            self.projects.operation(action, self.project)

    def session(self, path):
        return Programmer(self.client).load(self.network, '/db' + path)

    def prepare(self, address, unit_type, catalog, application, family):
        path = self.network + '/p/' + str(address)
        self.database.add(self.network, 'application', application, 'Lighting ' + str(application))
        self.database.create_unit(self.network, address, 'Tstat' + str(address), unit_type, '5.4.01',
                                  catalog_number=catalog)
        with self.session(path) as session:
            session.set('Application', str(application) + ' 255')
            session.set('ApplicationNumber', str(application))
            for name, value in UNRELATED.items():
                session.set(name, str(value))
            if family == 'programmable':
                session.set('EvapProgramEnabled', '1')
            session.save_to_source()
        return path

    def test_admitted_installations_replay_and_persist(self):
        address, application, units = 10, 56, []
        for unit_type, catalog, family, numbers in CASES:
            for number in numbers:
                units.append((self.prepare(address, unit_type, catalog, application, family),
                              family, number, application))
                address, application = address + 1, application + 1
        self.reload()
        for path, family, number, application in units:
            with self.session(path) as session:
                before = {n: v for n, v in session.values().items()}
            manager = NativeThermostatTemplates(self.client, self.catalog)
            plan = manager.plan(path, number, exclusive_project=True)
            document = plan.as_dict()
            self.assertTrue(document['original_post_load_adjustments_replayed'])
            result = manager.apply(plan, backup_project='B' + uuid4().hex[:7].upper())
            self.assertEqual(result['state'], 'verified_saved', result)
            self.assertTrue(result['output_groups_verified'])
            self.projects.operation('use', self.project)
            with self.session(path) as session:
                after = {n: v for n, v in session.values().items()}
            expected = plan.overlay.expected
            self.assertEqual({n: int(after[n], 0) for n in expected}, expected)
            self.assertEqual({n: v for n, v in after.items() if n not in expected},
                             {n: v for n, v in before.items() if n not in expected})
            self.assertEqual({n: int(after[n], 0) for n in UNRELATED}, UNRELATED)
            saved_groups = groups(self.database, self.network, application)
            hand = HAND.get((family, number))
            if hand is not None:
                values, tags = hand
                self.assertEqual({n: int(after[n], 0) for n in values}, values)
                self.assertEqual(saved_groups, tags)
            self.evidence['cases'].append({'path': path, 'family': family, 'template': number,
                                           'hand_checked': hand is not None,
                                           'post_load_changes': plan.overlay.post_load_changes,
                                           'groups': saved_groups, 'state': result['state']})

    def test_stale_relay_snapshot_replays_without_creating_stale_groups(self):
        # Native PP overlays replace these prior relay bytes. Static event
        # wiring and the offline post-overlay test independently prove that
        # the original template AfterLoad itself skips the relay getters.
        units = []
        stale = {f'InternalRelay{n}GroupNumber': 240 + n for n in range(1, 6)}
        for address, application, (unit_type, catalog, family, _numbers) in zip((50, 51), (83, 84), CASES):
            path = self.prepare(address, unit_type, catalog, application, family)
            with self.session(path) as session:
                for name, value in stale.items():
                    session.set(name, str(value))
                session.save_to_source()
            units.append((path, application, family))
        self.reload()
        results = []
        for path, application, family in units:
            with self.session(path) as session:
                before = dict(session.values())
            self.assertEqual({n: int(before[n], 0) for n in stale}, stale)
            manager = NativeThermostatTemplates(self.client, self.catalog)
            plan = manager.plan(path, 1, exclusive_project=True)
            result = manager.apply(plan, backup_project='B' + uuid4().hex[:7].upper())
            self.assertEqual(result['state'], 'verified_saved', result)
            self.projects.operation('use', self.project)
            with self.session(path) as session:
                after = dict(session.values())
            expected = plan.overlay.expected
            self.assertEqual({n: v for n, v in after.items() if n not in expected},
                             {n: v for n, v in before.items() if n not in expected})
            self.assertEqual([int(after[f'InternalRelay{n}GroupNumber'], 0) for n in range(1, 6)],
                             [1, 2, 3, 4, 255])
            saved_groups = groups(self.database, self.network, application)
            self.assertEqual(saved_groups, HAND[('programmable', 1)][1])
            self.assertTrue(set(stale.values()).isdisjoint(saved_groups))
            results.append({'path': path, 'family': family, 'template': 1,
                            'pre_load_relay_values': stale, 'groups': saved_groups,
                            'unrelated_parameters_preserved': True, 'state': result['state']})
        self.evidence['stale_relay_snapshots'] = results

    def test_outside_precondition_is_refused_without_writes(self):
        nine = self.prepare(40, 'PC_TSA', '5070THP,BK', 80, 'programmable')
        basic_nine = self.prepare(43, 'PC_TSB', '5070THB,BK', 82, 'basic')
        blank = self.network + '/p/41'
        self.database.create_unit(self.network, 41, 'NoApp', 'PC_TSB', '5.4.01', catalog_number='5070THB,BK')
        taken = self.prepare(42, 'PC_TSB', '5070THB,BK', 81, 'basic')
        self.database.add(self.network + '/81', 'group', 2, '[CG01] Old')
        self.reload()
        before = xml_text(self.database.get('//' + self.project, xml=True))
        refusals = []
        for path, number, text in ((nine, 9, 'GetNewGroup'), (basic_nine, 9, 'GetNewGroup'),
                                   (blank, 1, 'ApplicationNumber'),
                                   (taken, 1, 'CG01')):
            manager = NativeThermostatTemplates(self.client, self.catalog)
            with self.assertRaises(Exception) as caught:
                manager.plan(path, number, exclusive_project=True)
            self.assertIsInstance(caught.exception.cause, ThermostatTemplateError)
            self.assertIn(text, str(caught.exception.cause))
            refusals.append({'path': path, 'template': number, 'error': str(caught.exception.cause)})
        self.assertEqual(xml_text(self.database.get('//' + self.project, xml=True)), before)
        self.evidence['refusals'] = refusals

    def test_explicit_address_order_template_nine_cli_all_aliases(self):
        units = []
        aliases = (('PC_TSA', '5070THP,BK', 'programmable'), ('PC_TSA5', '5070THP,BK', 'programmable'),
                   ('PC_TSB', '5070THB,BK', 'basic'), ('PC_TSB5', '5070THB,BK', 'basic'))
        for index, (unit_type, catalog, family) in enumerate(aliases):
            path = self.prepare(60 + index, unit_type, catalog, 90 + index, family)
            units.append((path, unit_type, family, 90 + index))
        self.reload()
        cases = []
        for path, unit_type, family, application in units:
            with self.session(path) as session:
                before = dict(session.values())
            documents = []
            for action in ('preview', 'apply'):
                stdout, stderr = io.StringIO(), io.StringIO()
                arguments = ['thermostat', 'template', action, path, '--template', '9',
                             '--host', '127.0.0.1', '--port', str(self.service.port),
                             '--exclusive-project', '--spec-dir', SPEC_DIR,
                             '--group-sort', 'address-ascending']
                if action == 'apply':
                    arguments += ['--backup-project', 'B' + uuid4().hex[:7].upper()]
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = cli.main(arguments)
                self.assertEqual(code, 0, stderr.getvalue())
                documents.append(json.loads(stdout.getvalue()))
            preview, result = documents
            self.assertEqual(preview['post_load']['group_sort'], 'address-ascending')
            self.assertEqual(result['state'], 'verified_saved')
            self.assertTrue(result['output_groups_verified'])
            self.projects.operation('use', self.project)
            with self.session(path) as session:
                after = dict(session.values())
            expected = {**dict(self.catalog.load(family, 9).values), **preview['post_load']['parameters']}
            self.assertEqual({n: int(after[n], 0) for n in expected}, expected)
            self.assertEqual({n: v for n, v in after.items() if n not in expected},
                             {n: v for n, v in before.items() if n not in expected})
            self.assertEqual([int(after[f'InternalRelay{n}GroupNumber'], 0) for n in range(1, 6)],
                             [5, 2, 3, 6, 7])
            saved_groups = groups(self.database, self.network, application)
            self.assertEqual(saved_groups, {255: '<Unused>', 5: '[CG01] Y (cool)', 2: '[CG01] Y2 (cool)',
                                            3: '[CG01] G (fan)', 6: '[CG01] W (heat)', 7: '[CG01] W2 (heat)'})
            cases.append({'unit_type': unit_type, 'family': family, 'template': 9,
                          'group_sort': 'address-ascending', 'groups': saved_groups,
                          'unrelated_parameters_preserved': True, 'state': result['state']})
        self.evidence['explicit_address_order'] = cases

    def test_address_order_rejects_nonempty_or_stale_inventory(self):
        path = self.prepare(70, 'PC_TSA', '5070THP,BK', 95, 'programmable')
        self.reload()
        manager = NativeThermostatTemplates(self.client, self.catalog)
        plan = manager.plan(path, 9, exclusive_project=True, group_sort='address-ascending')
        self.database.add(self.network + '/95', 'group', 20, 'Concurrent addition')
        before = xml_text(self.database.get('//' + self.project, xml=True))
        with self.assertRaises(Exception) as caught:
            manager.apply(plan, backup_project='B' + uuid4().hex[:7].upper())
        self.assertIn('changed', str(caught.exception.cause))
        self.assertEqual(xml_text(self.database.get('//' + self.project, xml=True)), before)
        manager = NativeThermostatTemplates(self.client, self.catalog)
        with self.assertRaises(Exception) as caught:
            manager.plan(path, 9, exclusive_project=True, group_sort='address-ascending')
        self.assertIn('initially empty', str(caught.exception.cause))
        self.assertEqual(xml_text(self.database.get('//' + self.project, xml=True)), before)
        self.evidence['address_order_refusals'] = {'stale_inventory': True, 'nonempty_inventory': True,
                                                  'project_unchanged': True}

    def test_group_only_plan_is_applied_when_parameters_already_match(self):
        path = self.prepare(75, 'PC_TSB', '5070THB,BK', 96, 'basic')
        self.reload()
        first = NativeThermostatTemplates(self.client, self.catalog).plan(
            path, 9, exclusive_project=True, group_sort='address-ascending')
        with self.session(path) as session:
            for name, value in first.overlay.expected.items():
                session.set(name, str(value))
            session.save_to_source()
        self.reload()
        manager = NativeThermostatTemplates(self.client, self.catalog)
        plan = manager.plan(path, 9, exclusive_project=True, group_sort='address-ascending')
        self.assertEqual(plan.overlay.changes, ())
        self.assertTrue(plan.overlay.post_load.group_operations)
        self.assertTrue(plan.as_dict()['apply_would_mutate'])
        result = manager.apply(plan, backup_project='B' + uuid4().hex[:7].upper())
        self.assertEqual(result['state'], 'verified_saved')
        self.assertTrue(result['output_groups_verified'])
        self.projects.operation('use', self.project)
        self.assertEqual(groups(self.database, self.network, 96),
                         {255: '<Unused>', 5: '[CG01] Y (cool)', 2: '[CG01] Y2 (cool)',
                          3: '[CG01] G (fan)', 6: '[CG01] W (heat)', 7: '[CG01] W2 (heat)'})
        self.evidence['group_only_plan'] = {'parameter_changes': 0, 'groups_created': 6,
                                            'state': result['state']}

    def test_output_application_uses_scalar_thermostat_application_number(self):
        path = self.prepare(76, 'PC_TSA', '5070THP,BK', 97, 'programmable')
        self.database.add(self.network, 'application', 56, 'Generic Application decoy')
        self.database.add(self.network + '/56', 'group', 1, 'Preserve decoy')
        with self.session(path) as session:
            session.set('Application', '56 255')
            session.save_to_source()
        self.reload()
        decoy = xml_text(self.database.get(self.network + '/56', xml=True))
        manager = NativeThermostatTemplates(self.client, self.catalog)
        plan = manager.plan(path, 9, exclusive_project=True, group_sort='address-ascending')
        self.assertEqual(plan.overlay.application, 97)
        result = manager.apply(plan, backup_project='B' + uuid4().hex[:7].upper())
        self.assertEqual(result['state'], 'verified_saved')
        self.projects.operation('use', self.project)
        self.assertEqual(xml_text(self.database.get(self.network + '/56', xml=True)), decoy)
        self.assertEqual(groups(self.database, self.network, 97)[7], '[CG01] W2 (heat)')
        with self.session(path) as session:
            after = session.values()
        self.assertEqual(after['Application'], '0x38 0xff')
        self.assertEqual(int(after['ApplicationNumber'], 0), 97)
        self.evidence['application_number_selection'] = {
            'Application': 56, 'ApplicationNumber': 97, 'output_application': 97,
            'generic_application_unchanged': True, 'state': result['state']}


if __name__ == '__main__':
    unittest.main()
