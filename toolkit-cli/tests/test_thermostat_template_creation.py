"""One ordered thermostat template group-creation path.

Offline allocation/TagName/preservation cases plus a native database
roundtrip where CBUS_CGATE_TEST_HOST is set.  The creation plan audits the
replayed post-load group order with exact numeric allocation, requires an
explicit scalar Project.TagName, and is the save/reload preservation
reference.  No vendor specifications, physical thermostat, Launcher, CLI or
contract-inventory wiring is required.
"""
import os
import socket
import unittest
from uuid import uuid4
import xml.etree.ElementTree as ET

from cbus_toolkit.thermostat_post_load import (
    DAMPERS, OUTPUTS, RELAYS, GroupOperation, pp_name, replay_post_load)
from cbus_toolkit.thermostat_templates import (
    ThermostatTemplate, ThermostatTemplateError, plan_overlay,
    plan_template_group_creation)


def replay_values(**changes):
    values = {'InternalPlantType': 3, 'ZoneGroup': 1, 'ControlledZones': 3,
              'InternalPlantZones': 3, 'InternalPlantModes': 0, 'VentPlantType': 0,
              'DamperModulationEnable': 0, 'EvapProgramEnabled': 1, 'NonEvapProgramEnabled': 1}
    for side in ('Heating', 'Cooling'):
        values.update({side + 'PlantFanSpeedControlEnable': 0, side + 'PlantFanSpeeds': 1,
                       side + 'PlantFanDefaultSpeed': 1, side + 'PlantFanOnDelay': 0,
                       side + 'PlantFanOffDelay': 0, side + 'PlantFanEnable': 1})
    for attribute in OUTPUTS + DAMPERS + RELAYS:
        values.setdefault(pp_name(attribute), 255)
    return values | changes


def fixture_replay():
    return replay_post_load(replay_values(), 'programmable', 1, {255: '<Unused>'})


def fixture_template():
    return ThermostatTemplate('programmable', 1, 'THERMOSTATA_TEMPLATE01.xml', '0' * 64,
                              'Synthetic template', '0', '9', (('ZoneA', 5),))


def fixture_snapshot():
    replay = fixture_replay()
    base = {name: str(value) for name, value in replay_values().items()}
    for name in set(replay.expected) | {'ZoneA'}:
        base.setdefault(name, '0x0')
    base['ZoneA'] = '0x1'
    return base


# The plant-3 Basic Reverse Cycle replay creates these table-driven groups in
# table order against an otherwise unused application.
EXPECTED_GROUPS = {255: '<Unused>', 1: '[CG01] Y (heat/cool)', 2: '[CG01] B (cool activation)',
                   3: '[CG01] G (fan)', 4: '[CG01] B (heat activation)'}
EXPECTED_ORDER = [2, 1, 3, 4]


class TemplateGroupCreationTests(unittest.TestCase):
    def test_ordered_creation_binds_exact_allocation(self):
        replay = fixture_replay()
        self.assertEqual([(op.action, op.address) for op in replay.group_operations],
                         [('create', address) for address in EXPECTED_ORDER])
        plan = plan_template_group_creation(replay.group_operations, {255: '<Unused>'},
                                            project_tag_name='Thermostat Project', application=56)
        self.assertEqual(plan.project_tag_name, 'Thermostat Project')
        self.assertEqual(plan.application, 56)
        self.assertEqual(plan.expected_map, EXPECTED_GROUPS)
        self.assertEqual(plan.check_reloaded(dict(EXPECTED_GROUPS)), EXPECTED_GROUPS)
        document = plan.as_dict()
        self.assertEqual([row['address'] for row in document['ordered_operations']], EXPECTED_ORDER)
        self.assertEqual([row['position'] for row in document['ordered_operations']], [1, 2, 3, 4])
        self.assertTrue(all(row['previous_tag'] is None for row in document['ordered_operations']))
        self.assertEqual(document['expected_groups'], EXPECTED_GROUPS)

    def test_rename_keeps_its_declared_address(self):
        operations = (GroupOperation('create', 1, '[CG01] Y (heat/cool)'),
                      GroupOperation('rename', 0, '[CG01] W (heat)', 'Seed group'))
        plan = plan_template_group_creation(operations, {0: 'Seed group', 255: '<Unused>'},
                                            project_tag_name='Thermostat Project', application=56)
        self.assertEqual(plan.expected_map,
                         {0: '[CG01] W (heat)', 1: '[CG01] Y (heat/cool)', 255: '<Unused>'})
        receipts = plan.as_dict()['ordered_operations']
        self.assertEqual(receipts[1]['previous_tag'], 'Seed group')

    def test_project_tag_name_gate(self):
        replay = fixture_replay()
        for bad in (None, True, 7, b'Thermostat Project', ['Thermostat Project'],
                    {'tag': 'Thermostat Project'}):
            with self.subTest(tag=repr(bad)), self.assertRaisesRegex(
                    ThermostatTemplateError, 'Project.TagName'):
                plan_template_group_creation(replay.group_operations, {255: '<Unused>'},
                                             project_tag_name=bad, application=56)
        for bad_application in (None, True, '56', -1, 256, 56.0):
            with self.subTest(application=repr(bad_application)), self.assertRaisesRegex(
                    ThermostatTemplateError, 'application'):
                plan_template_group_creation(replay.group_operations, {255: '<Unused>'},
                                             project_tag_name='Thermostat Project',
                                             application=bad_application)

    def test_exact_allocation_refusals(self):
        base = {0: 'Seed group', 255: '<Unused>'}
        cases = [
            ((GroupOperation('create', 0, '[CG01] Y (heat/cool)'),), base, 'already allocated'),
            ((GroupOperation('create', 255, '[CG01] Extra'),), base, 'already allocated'),
            ((GroupOperation('create', 256, 'Group 256'),), base, 'integer byte'),
            ((GroupOperation('create', -1, 'Group -1'),), base, 'integer byte'),
            ((GroupOperation('create', 1, ''),), base, 'nonempty text'),
            ((GroupOperation('create', 1, '[CG01] Y (heat/cool)', 'stale'),), base,
             'no previous tag'),
            ((GroupOperation('rename', 9, '[CG01] Missing)', 'No group'),), base,
             'existing group'),
            ((GroupOperation('rename', 0, '[CG01] W (heat)', 'Wrong previous'),), base,
             'do not apply to this inventory'),
            ((GroupOperation('delete', 1, '[CG01] Y (heat/cool)'),), base,
             'Unknown template group creation'),
            (('create',), base, 'Unknown template group creation'),
        ]
        for operations, inventory, message in cases:
            with self.subTest(operations=repr(operations)), self.assertRaisesRegex(
                    ThermostatTemplateError, message):
                plan_template_group_creation(operations, inventory,
                                             project_tag_name='Thermostat Project', application=56)
        with self.assertRaisesRegex(ThermostatTemplateError, 'ordered operation history'):
            plan_template_group_creation(None, base, project_tag_name='Thermostat Project',
                                         application=56)
        with self.assertRaisesRegex(ThermostatTemplateError, 'exceeds 256'):
            plan_template_group_creation(
                [GroupOperation('create', address % 255, 'Group ' + str(n))
                 for n, address in enumerate(range(300))],
                {}, project_tag_name='Thermostat Project', application=56)
        for bad_base in (None, {0: None}, {'0': 'Seed group'}, {256: 'Group 256'}):
            with self.subTest(base=repr(bad_base)), self.assertRaisesRegex(
                    ThermostatTemplateError, 'Base groups'):
                plan_template_group_creation((), bad_base, project_tag_name='Thermostat Project',
                                             application=56)

    def test_reload_preservation_gate(self):
        plan = plan_template_group_creation(fixture_replay().group_operations, {255: '<Unused>'},
                                            project_tag_name='Thermostat Project', application=56)
        altered = {**EXPECTED_GROUPS, 2: '[CG01] Changed'}
        for reloaded, message in ((altered, 'differ from the creation plan'),
                                  ({k: v for k, v in EXPECTED_GROUPS.items() if k != 4},
                                   'differ from the creation plan'),
                                  ({**EXPECTED_GROUPS, 9: 'Extra group'},
                                   'differ from the creation plan')):
            with self.subTest(reloaded=repr(reloaded)), self.assertRaisesRegex(
                    ThermostatTemplateError, message):
                plan.check_reloaded(reloaded)
        for bad in (None, [(1, 'Group 1')], {'1': 'Group 1'}, {1: None}):
            with self.subTest(reloaded=repr(bad)), self.assertRaisesRegex(
                    ThermostatTemplateError, 'byte addresses to tag text'):
                plan.check_reloaded(bad)

    def test_plan_overlay_binds_creation_plan(self):
        template = fixture_template()
        overlay = plan_overlay(template, 'PC_TSA', '5.4.01', fixture_snapshot(),
                               groups={255: '<Unused>'}, application=56,
                               project_tag_name='Thermostat Project')
        self.assertEqual([op.address for op in overlay.creation_plan.operations], EXPECTED_ORDER)
        self.assertEqual(overlay.creation_plan.expected_map, EXPECTED_GROUPS)
        self.assertEqual(overlay.creation_plan.project_tag_name, 'Thermostat Project')
        self.assertIn(('ZoneA', 1, 5), overlay.changes)
        document = overlay.as_dict()
        self.assertEqual(document['post_load']['project_tag_name'], 'Thermostat Project')
        self.assertEqual(document['group_creation_plan']['expected_groups'], EXPECTED_GROUPS)

    def test_plan_overlay_without_tag_keeps_legacy_replay(self):
        overlay = plan_overlay(fixture_template(), 'PC_TSA', '5.4.01', fixture_snapshot(),
                               groups={255: '<Unused>'}, application=56)
        self.assertTrue(overlay.post_load.group_operations)
        self.assertIsNone(overlay.creation_plan)
        self.assertIsNone(overlay.project_tag_name)
        self.assertNotIn('group_creation_plan', overlay.as_dict())
        with self.assertRaisesRegex(ThermostatTemplateError, 'Project.TagName'):
            plan_overlay(fixture_template(), 'PC_TSA', '5.4.01', fixture_snapshot(),
                         groups={255: '<Unused>'}, application=56, project_tag_name=7)


def native_project_tag_name(project_xml):
    root = ET.fromstring(project_xml)
    projects = [node for node in root.iter() if node.tag == 'Project']
    if len(projects) != 1:
        return None
    tags = [node for node in projects[0] if node.tag == 'TagName']
    if len(tags) != 1 or not isinstance(tags[0].text, str):
        return None
    return tags[0].text


def native_output_groups(project_xml, network_address, application):
    root = ET.fromstring(project_xml)
    for network in root.iter('Network'):
        if network.findtext('Address') != str(network_address):
            continue
        for node in network.iter('Application'):
            if node.findtext('Address') == str(application):
                return {int(group.findtext('Address')): group.findtext('TagName')
                        for group in list(node) if group.tag in ('Group', 'NetVar')}
    return None


@unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST'),
                     'Set CBUS_CGATE_TEST_HOST for native template group creation')
class NativeTemplateGroupCreationTests(unittest.TestCase):
    def test_ordered_creation_with_tag_name_and_save_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        from cbus_toolkit.programming import xml_text

        host = os.environ['CBUS_CGATE_TEST_HOST']
        port = int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023'))
        client = CGateClient(host, port, timeout=30)
        self.addCleanup(client.close)
        client.connect()
        sentinel = socket.socket()
        self.addCleanup(sentinel.close)
        sentinel.bind(('127.0.0.1', 0))
        sentinel.listen(1)
        sentinel.settimeout(0.05)
        database, projects = NativeDatabase(client), NativeProjects(client)
        project = 'T' + uuid4().hex[:7].upper()
        projects.operation('new', project)
        self.addCleanup(self._delete_project, projects, project)
        network = '//' + project + '/254'
        database.create_network(project, 254, 'OwnedOffline', 'Cni',
                                '127.0.0.1:' + str(sentinel.getsockname()[1]))
        database.add(network, 'application', 56, 'Lighting')
        database.add(network + '/56', 'group', 0, 'Seed group')
        database.add(network + '/56', 'group', 255, '<Unused>')
        base = {0: 'Seed group', 255: '<Unused>'}
        operations = (GroupOperation('create', 1, '[CG01] Y (heat/cool)'),
                      GroupOperation('rename', 0, '[CG01] W (heat)', 'Seed group'))
        before_xml = xml_text(database.get('//' + project, xml=True))
        with self.assertRaisesRegex(ThermostatTemplateError, 'Project.TagName'):
            plan_template_group_creation(operations, base, project_tag_name=None, application=56)
        self.assertEqual(xml_text(database.get('//' + project, xml=True)), before_xml)
        tag = native_project_tag_name(before_xml)
        if tag is None:
            self.skipTest('Native fresh project has no scalar Project.TagName')
        plan = plan_template_group_creation(operations, base, project_tag_name=tag, application=56)
        applied = []
        for operation in plan.operations:
            if operation.action == 'create':
                database.add(network + '/56', 'group', operation.address, operation.tag)
            else:
                database.set(network + '/56/' + str(operation.address) + '/TagName',
                             operation.tag)
            applied.append((operation.action, operation.address))
        self.assertEqual(applied, [('create', 1), ('rename', 0)])
        for action in ('save', 'close', 'load'):
            projects.operation(action, project)
        projects.operation('use', project)
        after_xml = xml_text(database.get('//' + project, xml=True))
        reloaded = native_output_groups(after_xml, 254, 56)
        self.assertEqual(reloaded, {0: '[CG01] W (heat)', 1: '[CG01] Y (heat/cool)',
                                    255: '<Unused>'})
        self.assertEqual(plan.check_reloaded(reloaded), plan.expected_map)
        with self.assertRaisesRegex(ThermostatTemplateError, 'differ from the creation plan'):
            plan.check_reloaded({**reloaded, 1: '[CG01] Changed'})
        try:
            peer, _ = sentinel.accept()
        except socket.timeout:
            pass
        else:
            peer.close()
            self.fail('Closed template workflow connected to its CNI sentinel: object is not observable')

    @staticmethod
    def _delete_project(projects, project):
        for action in ('close', 'delete'):
            try:
                projects.operation(action, project)
            except Exception:
                pass


if __name__ == '__main__':
    unittest.main()
