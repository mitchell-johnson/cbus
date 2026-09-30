"""Owned native C-Gate acceptance for WGATE5F stored Scenes, without radio I/O."""
import hashlib
import json
import os
from pathlib import Path
import unittest

from cbus_toolkit.native import NativeDatabase
from cbus_toolkit.programming import Programmer, xml_text
from cbus_toolkit.unitspec import UnitSpecStore
from test_wireless_connection_native import (ClosedDatabaseClient, ClosedProject, ENABLED, raw_bytes, raw_text,
                                               staged_writes)


# Independent decoded-spec coordinates, deliberately not imported from the editor.
SCENE_FIELDS = {'SceneTriggerGroup': (0x130, 8), 'SceneTriggerLevel': (0x138, 8),
                'SceneTriggerRate': (0x140, 8), 'SceneVectorOffset': (0x150, 8), 'SceneVector': (0x158, 100)}
OLD_VECTOR = tuple((index * 7 + 11) % 255 for index in range(100))
TWO_SCENE_PREFIX = (7, 0, 9, 255, 255, 3, 128, 255)
TWO_SCENE_ARRAYS = {'SceneTriggerGroup': (10, 11, 255, 255, 255, 255, 255, 255),
                    'SceneTriggerLevel': (20, 21, 255, 255, 255, 255, 255, 255),
                    'SceneTriggerRate': (5, 0, 0, 0, 0, 0, 0, 0),
                    'SceneVectorOffset': (0, 133, 255, 255, 255, 255, 255, 255),
                    'SceneVector': TWO_SCENE_PREFIX + OLD_VECTOR[8:]}
TWO_SCENES = ({'application': 'primary', 'trigger_group': 10, 'trigger_level': 20, 'rate': 5,
               'entries': [{'group': 7, 'level': 0}, {'group': 9, 'level': 255}]},
              {'application': 'secondary', 'trigger_group': 11, 'trigger_level': 21, 'rate': 0,
               'entries': [{'group': 3, 'level': 128}]})
EMPTY_THIRD = {'application': 'primary', 'trigger_group': 255, 'trigger_level': 255, 'rate': 0, 'entries': []}


def integers(value):
    return tuple(int(part, 0) for part in value.split())


@unittest.skipUnless(ENABLED, 'Select an owned local native C-Gate and decoded specs for Scenes acceptance')
class WirelessScenesNativeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from research.local_cgate import LocalCGate
        cls.service = LocalCGate(os.environ['CBUS_LOCAL_CGATE_VENDOR'])
        cls.addClassCleanup(cls.service.close)
        (cls.service.work / 'config/access.txt').write_text('interface 127.0.0.1 Clipsal\n')
        cls.service.start()
        cls.store = UnitSpecStore(os.environ['CBUS_UNITSPEC_DIR'])

    def assert_closed(self, client, project):
        for network in (254, 200, 123, 99):
            for field, value in (('InterfaceState', 'closed'), ('TargetInterfaceState', 'closed'), ('SyncState', 'idle')):
                reply = client.command(f'GET //{project.name}/{network} {field}')
                self.assertTrue(any(f'{field}={value}'.lower() in line.lower() for line in reply.lines), reply.lines)

    def seed(self, pp):
        for name, value in (('Application', '56 57'), ('MapWirelessRemotes', '1'),
                            ('StatusMonitorApplication', '57'), ('ApplicationConnectEnabled', '1'),
                            ('ForwardingMode', '1'), ('SynchroniseToWired', '1'),
                            ('ForwardingRoute', '27 123 99 255 255 255 255')):
            pp.set(name, value)
        for remote in range(1, 9):
            pp.set(f'RemoteIdentity{remote}', f'{remote} 33 66 99')
            pp.set(f'GroupAddress{remote}', ' '.join(str(remote + index) for index in range(16)))
            pp.set(f'ApplicationSeconday{remote}', '0 1 0 1 0 1 0 1 0 1 0 1 0 1 0 1')
        for name, (_, size) in SCENE_FIELDS.items():
            values = OLD_VECTOR if name == 'SceneVector' else (0 if name == 'SceneTriggerRate' else 255,) * size
            pp.set(name, ' '.join(map(str, values)))

    def assert_preserved(self, pp, baseline):
        after = pp.values()
        names = sorted(set(baseline) - set(SCENE_FIELDS))
        self.assertEqual({name: after[name] for name in names}, {name: baseline[name] for name in names})
        return len(names)

    def assert_scene_arrays(self, pp, expected):
        actual = pp.values()
        for name, values in expected.items():
            address, count = SCENE_FIELDS[name]
            self.assertEqual(integers(actual[name]), tuple(values), name)
            self.assertEqual(raw_bytes(pp, address, count), bytes(values), name)

    def project_snapshot(self, client, project):
        from cbus_toolkit.wireless_scenes import FrozenSceneProject
        return FrozenSceneProject.from_xml(xml_text(NativeDatabase(client).get('//' + project.name, xml=True)).encode())

    def add_metadata(self, client, project):
        database = NativeDatabase(client)
        for application, groups in ((56, (7, 9)), (57, (3,)), (202, (10, 11, 255))):
            for group in groups:
                database.add(f'{project.network}/{application}', 'group', group, f'Group{group}')
        database.add(f'{project.network}/202/10', 'level', 20, 'Action20')
        # Action21 is deliberately added by the acceptance after the missing
        # metadata refusal; no placeholder facts are fabricated in the plan.

    def save_reload(self, client, project, pp, expected):
        """Save through one PP session; callers close it before project reload."""
        values, raw = pp.values(), raw_text(pp, 0x20, 0x1A0)
        self.assert_scene_arrays(pp, expected)
        checkpoint = len(client.commands)
        pp.save_to_source()
        self.assertEqual(sum(command.startswith('PP SAVE_TO_SOURCE ')
                             for command in client.commands[checkpoint:]), 1)
        return values, raw

    def reload(self, client, project, values, raw, expected):
        for action in ('SAVE', 'CLOSE', 'LOAD', 'USE'):
            client.command(f'PROJECT {action} {project.name}')
        with Programmer(client).load(project.network, project.path) as pp:
            self.assertEqual(pp.values(), values)
            self.assertEqual(raw_text(pp, 0x20, 0x1A0), raw)
            self.assert_scene_arrays(pp, expected)
        self.assert_closed(client, project)

    def exercise_editor(self, client, project, firmware, catalog):
        from cbus_toolkit.wireless_scenes import WirelessScenesEditor, WirelessScenesError, WirelessScenesPlan, native_project
        database = NativeDatabase(client)
        database.create_unit(project.network, 200, 'Scenes', 'WGATE5F', firmware, catalog_number=catalog)
        self.add_metadata(client, project)
        editor = WirelessScenesEditor(self.store.load('WGATE5X_2.xml'))
        context = {'source_network': 254, 'unit_address': 200, 'identity': ('WGATE5F', firmware, catalog)}
        report = {'unit_type': 'WGATE5F', 'firmware': firmware, 'catalog_number': catalog,
                  'physical_hardware_verified': False, 'saved_phases': []}
        self.assert_closed(client, project)
        with Programmer(client).load(project.network, project.path) as pp:
            self.seed(pp)
            before = pp.values()
            remote_raw, connection_raw = raw_text(pp, 0x70, 0xC0), raw_text(pp, 0x20, 0x30)
            missing_metadata = self.project_snapshot(client, project)
            checkpoint = len(client.commands)
            with self.assertRaises(WirelessScenesError):
                editor.plan(before, project=missing_metadata, scenes=list(TWO_SCENES), **context)
            self.assertEqual(client.commands[checkpoint:], [])
            report['missing_action_metadata_refused_before_io'] = True
            database.add(f'{project.network}/202/11', 'level', 21, 'Action21')
            frozen = self.project_snapshot(client, project)
            checkpoint = len(client.commands)
            plan = editor.plan(before, project=frozen, scenes=list(TWO_SCENES), **context)
            plan = WirelessScenesPlan.from_dict(json.loads(json.dumps(plan.as_dict())))
            self.assertEqual(client.commands[checkpoint:], [], 'Planning and document validation must be offline')
            self.assertEqual(tuple(plan.changes['SceneVector']), TWO_SCENE_ARRAYS['SceneVector'])
            for name, replacement in (('SceneVector', ' '.join(map(str, (77,) + OLD_VECTOR[1:]))),
                                      ('RemoteIdentity8', '9 33 66 99')):
                pp.set(name, replacement)
                stale = pp.values()
                checkpoint = len(client.commands)
                with self.assertRaises(WirelessScenesError):
                    editor.apply(pp, plan, project=frozen, exclusive_project=True)
                self.assertEqual(staged_writes(client.commands[checkpoint:]), [])
                self.assertEqual(pp.values(), stale)
                pp.set(name, before[name])
            report['stale_scene_and_remote_dependencies_refused_without_write'] = True
            database.add(f'{project.network}/56', 'group', 99, 'UnrelatedGroup99')
            fresh = self.project_snapshot(client, project)
            checkpoint = len(client.commands)
            with self.assertRaises(WirelessScenesError):
                editor.apply(pp, plan, project=fresh, exclusive_project=True)
            self.assertEqual(staged_writes(client.commands[checkpoint:]), [])
            self.assertEqual(pp.values(), before)
            report['stale_project_refused_without_write'] = True
            plan = editor.plan(before, project=fresh, scenes=list(TWO_SCENES), **context)
            checked = native_project(pp, plan, exclusive_project=True)
            self.assertTrue(editor.apply(pp, plan, project=checked, exclusive_project=True)['verified'])
            self.assert_scene_arrays(pp, TWO_SCENE_ARRAYS)
            self.assertEqual(raw_text(pp, 0x70, 0xC0), remote_raw)
            self.assertEqual(raw_text(pp, 0x20, 0x30), connection_raw)
            report['unrelated_parameters_preserved'] = self.assert_preserved(pp, before)
            report['two_scene_vector_prefix_hex'] = bytes(TWO_SCENE_PREFIX).hex().upper()
            report['unused_vector_tail_preserved'] = True
            report['secondary_offset_raw'] = 133
            values, raw = self.save_reload(client, project, pp, TWO_SCENE_ARRAYS)
        self.reload(client, project, values, raw, TWO_SCENE_ARRAYS)
        report['saved_phases'].append('two-scenes-primary-secondary-with-level255')

        third_arrays = dict(TWO_SCENE_ARRAYS, SceneVectorOffset=(0, 133, 8, 255, 255, 255, 255, 255),
                            SceneVector=TWO_SCENE_PREFIX + (255,) + OLD_VECTOR[9:])
        with Programmer(client).load(project.network, project.path) as pp:
            frozen = self.project_snapshot(client, project)
            plan = editor.plan(pp.values(), project=frozen, scenes=[*TWO_SCENES, EMPTY_THIRD], **context)
            checked = native_project(pp, plan, exclusive_project=True)
            self.assertTrue(editor.apply(pp, plan, project=checked, exclusive_project=True)['verified'])
            self.assert_scene_arrays(pp, third_arrays)
            self.assert_preserved(pp, before)
            values, raw = self.save_reload(client, project, pp, third_arrays)
        self.reload(client, project, values, raw, third_arrays)
        report['saved_phases'].append('third-empty-scene-terminator-with-preserved-tail')

        empty_arrays = {name: ((0,) * 8 if name == 'SceneTriggerRate' else (255,) * 8)
                        for name in SCENE_FIELDS if name != 'SceneVector'}
        empty_arrays['SceneVector'] = third_arrays['SceneVector']
        with Programmer(client).load(project.network, project.path) as pp:
            frozen = self.project_snapshot(client, project)
            plan = editor.plan(pp.values(), project=frozen, scenes=[], **context)
            checked = native_project(pp, plan, exclusive_project=True)
            self.assertTrue(editor.apply(pp, plan, project=checked, exclusive_project=True)['verified'])
            self.assert_scene_arrays(pp, empty_arrays)
            self.assert_preserved(pp, before)
            self.assertEqual(raw_text(pp, 0x70, 0xC0), remote_raw)
            self.assertEqual(raw_text(pp, 0x20, 0x30), connection_raw)
            values, raw = self.save_reload(client, project, pp, empty_arrays)
        self.reload(client, project, values, raw, empty_arrays)
        report['saved_phases'].append('clear-scene-list-with-complete-vector-preserved')
        report['all_phases_save_close_reload_verified'] = True
        report['all_networks_closed_and_idle'] = True
        report['connection_route_and_remote_mappings_preserved'] = True
        return report

    def probe_native_arrays(self, client, project):
        """Pin permissive native PP semantics separately from the bounded scene API."""
        NativeDatabase(client).create_unit(project.network, 200, 'ArrayProbe', 'WGATE5F', '2.4.00',
                                           catalog_number='5800WCGA')
        report = {'unit_type': 'WGATE5F', 'firmware': '2.4.00', 'probes': [],
                  'scope': 'Native PP array transport only; not the original Toolkit scene serializer'}
        self.assert_closed(client, project)
        with Programmer(client).load(project.network, project.path) as pp:
            for name, (address, count) in SCENE_FIELDS.items():
                baseline = tuple(range(1, count + 1))
                for label, sent, expected in (('short', (201, 202, 203), (201, 202, 203) + baseline[3:]),
                                              ('empty', (), baseline),
                                              ('oversized', (42,) * (count + 1), (42,) * count)):
                    pp.set(name, ' '.join(map(str, baseline)))
                    before = pp.values()
                    pp.set(name, ' '.join(map(str, sent)))
                    after = pp.values()
                    self.assertEqual(integers(after[name]), expected)
                    self.assertEqual(raw_bytes(pp, address, count), bytes(expected))
                    self.assertEqual({key: value for key, value in after.items() if key != name},
                                     {key: value for key, value in before.items() if key != name})
                    report['probes'].append({'parameter': name, 'case': label, 'sent_count': len(sent),
                                             'read_count': len(expected), 'accepted': True,
                                             'raw_bytes_verified': True, 'unrelated_parameters_preserved': True})
            final, raw = pp.values(), raw_text(pp, 0x130, 0x8C)
            pp.save_to_source()
        for action in ('SAVE', 'CLOSE', 'LOAD', 'USE'):
            client.command(f'PROJECT {action} {project.name}')
        with Programmer(client).load(project.network, project.path) as pp:
            self.assertEqual(pp.values(), final)
            self.assertEqual(raw_text(pp, 0x130, 0x8C), raw)
        self.assert_closed(client, project)
        report['save_close_reload_passed'] = True
        return report

    def test_native_scene_arrays_editor_preservation_and_reload(self):
        report = {'format': 'cbus-wireless-scenes-native-acceptance-v1', 'backend': 'local',
                  'scope': 'Owned native C-Gate closed synthetic database projects; no radio or physical network',
                  'executed_test_id': ('tests/test_wireless_scenes_native.py::WirelessScenesNativeTest::'
                                       'test_native_scene_arrays_editor_preservation_and_reload'),
                  'original_toolkit_gui_executed': False, 'physical_hardware_verified': False,
                  'types': [], 'passed': False}
        root = Path(__file__).resolve().parents[1]
        report['source_sha256'] = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in (
            'src/cbus_toolkit/wireless_scenes.py', 'src/cbus_toolkit/wireless_gateway.py',
            'src/cbus_toolkit/wireless_connection.py', 'tests/test_wireless_scenes_native.py',
            'tests/test_wireless_connection_native.py')}
        with ClosedDatabaseClient('127.0.0.1', self.service.port, timeout=30) as client:
            report['greeting'] = client.greeting
            with ClosedProject(client) as project:
                report['native_array_transport'] = self.probe_native_arrays(client, project)
            for firmware, catalog in (('2.2.90', '5800WCGA'), ('2.4.00', 'SLC5800WCGD')):
                with self.subTest(firmware=firmware), ClosedProject(client) as project:
                    report['types'].append(self.exercise_editor(client, project, firmware, catalog))
            self.assertFalse(any(command.upper().startswith('NET OPEN') for command in client.commands))
            report['network_open_commands'] = 0
        self.service.close()
        report['service'] = {name: self.service.report[name] for name in (
            'vendor_jar_sha256', 'java_version', 'listener_ownership_verified', 'projects_adopted',
            'cleanup_complete', 'process_exit_confirmed', 'work_removed')}
        for name in ('listener_ownership_verified', 'cleanup_complete', 'process_exit_confirmed', 'work_removed'):
            self.assertTrue(report['service'][name])
        report['passed'] = len(report['types']) == 2 and all(row['all_phases_save_close_reload_verified']
                                                          for row in report['types'])
        self.assertTrue(report['passed'])
        if os.environ.get('CBUS_WIRELESS_SCENES_REPORT'):
            Path(os.environ['CBUS_WIRELESS_SCENES_REPORT']).write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    unittest.main()
