"""Actual owned XML/API persistence with authored metadata listener contexts."""
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
import unittest

from cbus_toolkit.cgate import CGateResponse
from cbus_toolkit.native import NativeDatabase
from cbus_toolkit.project import ProjectDocument, _all_elements, _oid
from cbus_toolkit.senlla_inherited_owner import SENLLAInheritedOwner
from cbus_toolkit.senlla_project_bridge import MetadataOwnerRequired, SENLLAProjectBridge
from cbus_toolkit.sensors import SensorError
from test_senlla_inherited_owner import document, snapshot, english_metadata_name


def quiet_metadata_owner(request, bridge, runtime):
    """Authored zero-listener context, not native construction acceptance."""


class OwnedNativeClient:
    """Existing NativeDatabase APIs against one authored owned document."""
    def __init__(self, project, path):
        self.project, self.path = project, path
        self.commands = []
        self.existing_receipt = None
        self.fail_save = False

    def command(self, command):
        self.commands.append(command)
        if command.startswith('DBGETXML '):
            xml = self.project.to_xml_bytes().decode('utf-8')
            return CGateResponse(tuple('347-' + line for line in xml.splitlines()), '200 OK', 200)
        if command.startswith('DBADDSAFE '):
            _, parent, kind, address, name = command.split(' ', 4)
            path = '/network/' + parent.split('/')[3]
            if len(parent.split('/')) > 4:
                path += '/application/' + parent.split('/')[4]
            if len(parent.split('/')) > 5:
                path += '/group/' + parent.split('/')[5]
            result = self.project.add('group' if kind == 'NetVar' else kind.lower(), path,
                                      address=int(address), name=name)
            node = self.project.resolve(result['path'])
            oid = str(uuid4())
            self.project.set_field(result['path'], '@OID', oid)
            if kind == 'NetVar':
                node.tagName = node.nodeName = 'NetVar'
            if kind == 'Level':
                node.removeAttribute('Value')  # actual API must initialize it
            final = '301 OID=' + (self.existing_receipt or oid)
            return CGateResponse((final,), final, 301)
        if command.startswith('DBGET !'):
            oid = command.split('!', 1)[1].split('/')[0]
            found = any(_oid(node) == oid for node in _all_elements(self.project.project))
            return CGateResponse((), ('342 OID=' + oid) if found else '401 Missing', 342 if found else 401)
        if command.startswith('DBSETSAFE !'):
            identity, value = command.split(' ', 2)[1:]
            oid = identity[1:].split('/')[0]
            node = next(node for node in _all_elements(self.project.project) if _oid(node) == oid)
            self.project.set_field(self.project.path_of(node), 'Value', value)
            return CGateResponse((), '200 OK', 200)
        if command == 'PROJECT SAVE SITE':
            if self.fail_save:
                return CGateResponse((), '401 Save failed', 401)
            self.project.save(self.path)
            return CGateResponse((), '200 OK', 200)
        raise AssertionError('Unexpected authored command: ' + command)


class SENLLAProjectBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'owned.xml'
        self.project = document(self.path)

    def bridge(self, **providers):
        providers.setdefault('creation_dispatch', quiet_metadata_owner)
        providers.setdefault('metadata_name', english_metadata_name)
        bridge = SENLLAProjectBridge.from_document(self.project, 254, 42,
                                                   storage_path=self.path, **providers)
        owner = SENLLAInheritedOwner(snapshot(), bridge)
        return bridge, owner.runtime

    def test_missing_false_probe_confirms_absence_without_storage_or_registration(self):
        bridge, runtime = self.bridge()
        before = self.path.read_bytes()
        self.assertIsNone(runtime.get_source_application(56, create=False, source='literal.false'))
        self.assertEqual(runtime.apps, {})
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual([row['operation'] for row in bridge.events], ['actual_metadata_lookup'])

    def test_missing_metadata_requires_actual_listener_owner_even_in_prekey(self):
        bridge, runtime = self.bridge(creation_dispatch=None)
        before = self.path.read_bytes()
        with self.assertRaises(MetadataOwnerRequired) as raised:
            runtime.get_source_application(56, source='literal.create')
        self.assertEqual(raised.exception.request['stage'], 'before_backend_creation')
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(runtime.apps, {})

    def test_application_group_and_action_create_save_readback_causally(self):
        bridge, runtime = self.bridge()
        app = runtime.get_source_application(202, source='literal.trigger_app')
        self.assertEqual(bridge.current_record(runtime, app)['tag_name'], 'Trigger Control')
        self.assertEqual(runtime.groups, {})
        group = runtime.get_source_group(app, 7, source='literal.trigger_group')
        self.assertEqual(bridge.current_record(runtime, group)['tag_name'], 'Trigger Group 7')
        self.assertEqual(runtime.levels, {})
        level = bridge.get_level(runtime, group, 255, source='literal.invoke_level')
        self.assertEqual(bridge.current_record(runtime, level)['value'], '255')
        self.assertEqual(bridge.current_record(runtime, level)['tag_name'], 'Action Selector 255')
        self.assertIs(bridge.get_level(runtime, group, 255, source='literal.repeat'), level)
        self.assertEqual(ProjectDocument.load(self.path).get(
        '/network/254/application/202/group/7/level/255')['fields']['TagName'], 'Action Selector 255')
        self.assertEqual([row['kind'] for row in bridge.events
                          if row['operation'] == 'metadata_storage_readback'],
                         ['application', 'group', 'level'])

    def test_native_standard_names_and_unused_objects_are_actual_manager_members(self):
        bridge, runtime = self.bridge()
        for address, name in ((56, 'Lighting'), (57, '57'), (95, 'DALI'),
                              (203, 'Enable Control'), (255, '<Unused>')):
            with self.subTest(address=address):
                app = runtime.get_source_application(address, source='literal.app')
                self.assertEqual(bridge.current_record(runtime, app)['tag_name'], name)
                unused = runtime.get_source_group(app, 255, source='literal.unused')
                self.assertEqual(bridge.current_record(runtime, unused)['tag_name'], '<Unused>')
                self.assertIs(runtime.groups[(address, 255)], unused)
        bridge.metadata_name_provider = None
        with self.assertRaisesRegex(SensorError, 'registry/resource descriptor'):
            runtime.get_source_application(172, source='literal.needs_descriptor')

    def test_existing_metadata_is_current_and_not_prefetched(self):
        self.project.add('application', '/network/254', address=56, name='Current lighting')
        self.project.add('group', '/network/254/application/56', address=20, name='Twenty')
        self.project.add('group', '/network/254/application/56', address=7, name='Seven')
        bridge, runtime = self.bridge(creation_dispatch=None)
        app = runtime.get_source_application(56, create=False, source='literal.actual_app')
        self.assertEqual(runtime.groups, {})
        group = runtime.get_source_group(app, 20, create=False, source='literal.actual_group')
        self.assertEqual(set(runtime.groups), {(56, 20)})
        self.project.set_field('/network/254/application/56/group/20', 'TagName', 'Changed')
        self.assertEqual(bridge.current_record(runtime, group)['tag_name'], 'Changed')
        self.assertIs(runtime.get_source_group(app, 20, source='literal.same'), group)

    def test_existing_action_address_and_current_value_are_distinct_source_facts(self):
        self.project.add('application', '/network/254', address=202, name='Trigger Control')
        self.project.add('group', '/network/254/application/202', address=7, name='Trigger Group 7')
        self.project.add('level', '/network/254/application/202/group/7', address=22, name='Existing')
        self.project.set_field('/network/254/application/202/group/7/level/22', '@Value', 15)
        bridge, runtime = self.bridge(creation_dispatch=None)
        app = runtime.get_source_application(202, source='literal.app')
        group = runtime.get_source_group(app, 7, source='literal.group')
        level = bridge.get_level(runtime, group, 22, source='literal.existing_level')
        self.assertEqual(level.identity, (202, 7, 22))
        self.assertEqual(bridge.current_record(runtime, level)['value'], '15')
        self.assertEqual(bridge.level_value(runtime, level), 15)
        self.project.set_field('/network/254/application/202/group/7/level/22', '@Value', 33)
        self.assertEqual(bridge.level_value(runtime, level), 33)
        self.assertFalse(any(row['operation'] == 'backend_metadata_created' for row in bridge.events))

    def test_actual_group_order_and_to_string_are_explicit_current_providers(self):
        self.project.add('application', '/network/254', address=56, name='Lighting')
        for address in (20, 7, 255):
            self.project.add('group', '/network/254/application/56', address=address,
                             name='G' + str(address))
        bridge, runtime = self.bridge(manager_order=lambda app, rows, runtime: (7, 255, 20),
                                     display_text=lambda obj, row, source, runtime:
                                     row['tag_name'] + ' [' + str(row['address']) + ']')
        apps = bridge.form_applications(runtime)
        self.assertEqual([group.address for group in apps[0].groups], [7, 255, 20])
        self.assertEqual([group.tag_name for group in apps[0].groups], ['G7', 'G255', 'G20'])
        self.assertEqual(bridge.display_text(runtime, runtime.groups[(56, 7)], source='literal.display'),
                         'G7 [7]')
        before = runtime.groups[(56, 20)]
        record = bridge.current_record(runtime, before)
        record['fields']['TagName'] = 'BAD'
        self.assertEqual(bridge.current_record(runtime, before)['tag_name'], 'G20')
        runtime.get_source_group(runtime.apps[56], 8, source='literal.new_group')
        with self.assertRaisesRegex(SensorError, 'order'):
            runtime.current_source_group_order(runtime.apps[56])

    def test_form_inventory_cannot_invent_order_or_use_tag_name_as_to_string(self):
        self.project.add('application', '/network/254', address=56, name='Lighting')
        self.project.add('group', '/network/254/application/56', address=7, name='Seven')
        bridge, runtime = self.bridge()
        with self.assertRaisesRegex(SensorError, 'Items order'):
            bridge.form_applications(runtime)
        bridge.manager_order = lambda app, rows, runtime: (7,)
        bridge.form_applications(runtime)
        with self.assertRaisesRegex(SensorError, 'ToString'):
            bridge.display_text(runtime, runtime.groups[(56, 7)], source='literal.display')

    def test_scoped_current_group_items_do_not_seed_unrelated_apps_or_levels(self):
        for address in (56, 57, 202):
            self.project.add('application', '/network/254', address=address, name='App ' + str(address))
        for address in (20, 7, 255):
            self.project.add('group', '/network/254/application/56', address=address, name='G' + str(address))
        self.project.add('group', '/network/254/application/57', address=8, name='Other')
        self.project.add('group', '/network/254/application/202', address=9, name='Trigger')
        self.project.add('level', '/network/254/application/202/group/9', address=22, name='Action')
        calls = []
        def order(app, rows, runtime):
            calls.append((app, [row['address'] for row in rows]))
            return (7, 255, 20)
        bridge, runtime = self.bridge(manager_order=order, creation_dispatch=None)
        app = runtime.get_source_application(56, create=False, source='literal.existing_app')
        groups = bridge.group_items(runtime, app)
        self.assertEqual([group.identity for group in groups], [(56, 7), (56, 255), (56, 20)])
        self.assertIs(calls[0][0], app)
        self.assertEqual(calls[0][1], [20, 7, 255])
        self.assertEqual(tuple(runtime.apps), (56,))
        self.assertEqual(set(runtime.groups), {(56, 7), (56, 255), (56, 20)})
        self.assertEqual(runtime.levels, {})
        self.assertIs(runtime.current_source_group_order(app)[0], groups[0])
        self.assertFalse(any(event['operation'] == 'backend_metadata_created' for event in bridge.events))

    def test_scoped_items_reread_current_metadata_and_retain_same_objects(self):
        self.project.add('application', '/network/254', address=56, name='Lighting')
        self.project.add('group', '/network/254/application/56', address=7, name='Seven')
        order = [7]
        bridge, runtime = self.bridge(manager_order=lambda app, rows, runtime: tuple(order))
        app = runtime.get_source_application(56, source='literal.app')
        before = bridge.group_items(runtime, app)
        self.project.add('group', '/network/254/application/56', address=20, name='Twenty')
        order[:] = [20, 7]
        after = bridge.group_items(runtime, app)
        self.assertEqual([group.identity[1] for group in after], [20, 7])
        self.assertIs(before[0], after[1])
        self.project.set_field('/network/254/application/56/group/7', 'TagName', 'Changed')
        self.assertEqual(bridge.current_record(runtime, after[1])['tag_name'], 'Changed')
        self.assertEqual(bridge.group_items(runtime, app), after)

    def test_scoped_items_require_actual_canonical_app_and_order_provider(self):
        from cbus_toolkit.senlla_key_events import _Object
        self.project.add('application', '/network/254', address=56, name='Lighting')
        self.project.add('group', '/network/254/application/56', address=7, name='Seven')
        bridge, runtime = self.bridge()
        app = runtime.get_source_application(56, source='literal.app')
        with self.assertRaisesRegex(SensorError, 'Items order'):
            bridge.group_items(runtime, app)
        bridge.manager_order = lambda app, rows, runtime: (7,)
        with self.assertRaisesRegex(SensorError, 'SAME canonical'):
            bridge.group_items(runtime, _Object('application', 56))
        self.assertEqual(bridge.group_items(runtime, app), (runtime.groups[(56, 7)],))
        bridge.manager_order = lambda app, rows, runtime: ()
        with self.assertRaisesRegex(SensorError, 'currently registered'):
            bridge.group_items(runtime, app)

    def test_nested_creation_can_rebind_current_block_application_before_second_getter(self):
        switched = []
        def observe(request, bridge, runtime):
            if (request.kind == 'group' and request.application == 56 and request.address == 255
                    and request.stage == 'stored_readback' and not switched):
                switched.append(True)
                runtime.blocks[0].application.set(runtime.apps[57])
        bridge, runtime = self.bridge(creation_dispatch=observe)
        app56 = runtime.get_source_application(56, source='literal.first_app')
        app57 = runtime.get_source_application(57, source='literal.second_app')
        runtime.blocks[0].application.set(app56)
        self.assertIs(runtime.blocks[0].application._value, app57)
        self.assertIs(runtime.blocks[0].group._value, runtime.groups[(57, 255)])
        self.assertEqual(set(runtime.groups), {(56, 255), (57, 255)})

    def test_foreign_pointer_duplicate_identity_and_unit_identity_fail_closed(self):
        bridge, runtime = self.bridge()
        app = runtime.get_source_application(56, source='literal.app')
        group = runtime.get_source_group(app, 7, source='literal.group')
        from cbus_toolkit.senlla_key_events import _Object
        with self.assertRaisesRegex(SensorError, 'SAME canonical'):
            bridge.get_level(runtime, _Object('group', group.identity), 1, source='literal.foreign')
        with self.assertRaisesRegex(SensorError, 'actual level'):
            bridge.level_value(runtime, group)
        self.project.set_field('/network/254/unit/42', 'UnitType', 'SENLL')
        with self.assertRaisesRegex(SensorError, 'Unit identity'):
            SENLLAInheritedOwner(snapshot(), SENLLAProjectBridge.from_document(
                self.project, 254, 42, storage_path=self.path))

    def test_actual_native_api_add_level_initialize_save_and_readback(self):
        client = OwnedNativeClient(self.project, self.path)
        bridge = SENLLAProjectBridge.from_native(NativeDatabase(client), 'SITE', 254, 42,
                                                 creation_dispatch=quiet_metadata_owner,
                                                 metadata_name=english_metadata_name)
        runtime = SENLLAInheritedOwner(snapshot(), bridge).runtime
        app = runtime.get_source_application(202, source='literal.app')
        group = runtime.get_source_group(app, 7, source='literal.group')
        level = bridge.get_level(runtime, group, 22, source='literal.level')
        self.assertEqual(bridge.current_record(runtime, level)['value'], '22')
        self.assertEqual([line for line in client.commands if line.startswith('DBADDSAFE')],
                         ['DBADDSAFE //SITE/254 Application 202 Trigger Control',
                          'DBADDSAFE //SITE/254/202 Group 7 Trigger Group 7',
                          'DBADDSAFE //SITE/254/202/7 Level 22 Action Selector 22'])
        self.assertEqual(client.commands.count('PROJECT SAVE SITE'), 3)
        self.assertEqual(len([line for line in client.commands if line.startswith('DBSETSAFE !')]), 1)
        self.assertFalse(bridge.evidence()['native_storage_acceptance'])

    def test_existing_oid_receipt_is_rejected_before_level_identity_or_value_io(self):
        self.project.add('application', '/network/254', address=202, name='Trigger Control')
        self.project.add('group', '/network/254/application/202', address=7, name='Trigger Group 7')
        existing = str(uuid4())
        self.project.set_field('/network/254/unit/42', '@OID', existing)
        client = OwnedNativeClient(self.project, self.path)
        client.existing_receipt = existing
        bridge = SENLLAProjectBridge.from_native(NativeDatabase(client), 'SITE', 254, 42,
                                                 creation_dispatch=quiet_metadata_owner,
                                                 metadata_name=english_metadata_name)
        runtime = SENLLAInheritedOwner(snapshot(), bridge).runtime
        app = runtime.get_source_application(202, source='literal.app')
        group = runtime.get_source_group(app, 7, source='literal.group')
        with self.assertRaisesRegex(SensorError, 'existing OID'):
            bridge.get_level(runtime, group, 1, source='literal.level')
        self.assertEqual(runtime.levels, {})
        self.assertTrue(bridge.failed)
        self.assertFalse(any(line.startswith(('DBGET !', 'DBSETSAFE !', 'DBDELETE', 'PROJECT SAVE'))
                             for line in client.commands))

    def test_actual_native_enable_application_creates_netvar_metadata(self):
        client = OwnedNativeClient(self.project, self.path)
        bridge = SENLLAProjectBridge.from_native(NativeDatabase(client), 'SITE', 254, 42,
                                                 creation_dispatch=quiet_metadata_owner,
                                                 metadata_name=english_metadata_name)
        runtime = SENLLAInheritedOwner(snapshot(), bridge).runtime
        app = runtime.get_source_application(203, source='literal.enable_app')
        group = runtime.get_source_group(app, 7, source='literal.enable_group')
        record = bridge.current_record(runtime, group)
        self.assertEqual((record['kind'], record['tag_name']), ('NetVar', 'Enable Network Variable 7'))
        self.assertIn('DBADDSAFE //SITE/254/203 NetVar 7 Enable Network Variable 7', client.commands)

    def test_storage_failure_preserves_partial_backend_truth_and_refuses_replay(self):
        client = OwnedNativeClient(self.project, self.path)
        client.fail_save = True
        bridge = SENLLAProjectBridge.from_native(NativeDatabase(client), 'SITE', 254, 42,
                                                 creation_dispatch=quiet_metadata_owner,
                                                 metadata_name=english_metadata_name)
        runtime = SENLLAInheritedOwner(snapshot(), bridge).runtime
        with self.assertRaisesRegex(RuntimeError, 'Save failed'):
            runtime.get_source_application(56, source='literal.app')
        self.assertEqual(runtime.apps, {})
        self.assertTrue(bridge.failed)
        self.assertEqual(self.project.get('/network/254/application/56')['fields']['TagName'], 'Lighting')
        with self.assertRaises(SensorError):
            bridge.dispatch(None, runtime)
        self.assertFalse(bridge.evidence()['complete_toolkit_save'])


if __name__ == '__main__':
    unittest.main()
