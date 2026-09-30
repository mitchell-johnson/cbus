"""Owned native WGATE5N base Connection acceptance; closed database only."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
import zipfile

from cbus_toolkit.native import NativeDatabase
from cbus_toolkit.programming import Programmer, xml_text
from cbus_toolkit.unitspec import UnitSpecStore
import test_wireless_connection_native as connection_native
from test_wireless_connection_native import (
    ClosedProject, ClosedDatabaseClient, ENABLED, raw_text, raw_bytes, staged_writes,
)


@unittest.skipUnless(ENABLED, 'Select an owned local native C-Gate and decoded specs for Connection acceptance')
class WirelessBaseConnectionNativeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from research.local_cgate import LocalCGate
        cls.service = LocalCGate(os.environ['CBUS_LOCAL_CGATE_VENDOR'])
        cls.addClassCleanup(cls.service.close)
        (cls.service.work / 'config/access.txt').write_text('interface 127.0.0.1 Clipsal\n')
        cls.service.start()
        cls.store = UnitSpecStore(os.environ['CBUS_UNITSPEC_DIR'])

    def seed(self, pp):
        connection_native.WirelessConnectionNativeTest.seed(self, pp)
        pp.set('MapWirelessRemotes', '1')

    def assert_unchanged(self, pp, baseline, owned):
        after = pp.values()
        preserved = sorted(set(baseline) - set(owned))
        self.assertEqual({name: after[name] for name in preserved},
                         {name: baseline[name] for name in preserved})
        return len(preserved)

    def assert_closed(self, client, project):
        for network in (254, 200, 123, 99):
            for field, value in (('InterfaceState', 'closed'), ('TargetInterfaceState', 'closed'), ('SyncState', 'idle')):
                reply = client.command(f'GET //{project.name}/{network} {field}')
                self.assertTrue(any(f'{field}={value}'.lower() in line.lower() for line in reply.lines), reply.lines)

    def exercise(self, client, project, firmware, catalog):
        from cbus_toolkit.wireless_connection import (
            OWNED, WirelessConnectionEditor, WirelessConnectionError, WirelessConnectionPlan)
        database = NativeDatabase(client)
        database.create_unit(project.network, 200, 'Gateway', 'WGATE5N', firmware, catalog_number=catalog)
        editor = WirelessConnectionEditor(self.store.load('WGATE5X_2.xml'))
        case = {'unit_type': 'WGATE5N', 'firmware': firmware, 'catalog_number': catalog,
                'raw_byte_assertions': 0, 'physical_hardware_verified': False}
        self.assert_closed(client, project)
        with Programmer(client).load(project.network, project.path) as pp:
            topology = project.topology()
            identity = ('WGATE5N', firmware, catalog)
            empty_plan = editor.plan(pp.values(), topology=topology, source_network=254, unit_address=200,
                                     identity=identity, application1=56, application2=202)
            self.assertTrue(editor.apply(pp, empty_plan, topology=topology, exclusive_project=True)['verified'])
            self.assertEqual(raw_bytes(pp, 0x21, 2), bytes((56, 202)))
            case['empty_remote_application_edit_verified'] = True
            self.seed(pp)
            before = pp.values()
            remote_raw = raw_text(pp, 0x70, 0x150)
            topology = project.topology()
            options = {'topology': topology, 'source_network': 254, 'unit_address': 200,
                       'identity': identity, 'application1': 56, 'application2': 202,
                       'adjacent_network': True, 'synchronise_to_wired': True,
                       'destination_network': 99, 'status_monitor_application': 57}
            checkpoint = len(client.commands)
            plan = editor.plan(before, **options)
            document = json.loads(json.dumps(plan.as_dict()))
            plan = WirelessConnectionPlan.from_dict(document)
            self.assertEqual(client.commands[checkpoint:], [], 'Planning must be offline')
            self.assertEqual(tuple(plan.changes['ForwardingRoute']), (27, 123, 99, 255, 255, 255, 255))
            self.assertEqual(set(plan.expected), set(OWNED))
            # Base Connection has no advanced application callbacks. A complete
            # native snapshot retains remote/scene values as opaque state.
            opaque = {**before, 'RemoteIdentity1': 'opaque remote state',
                      'SceneVectorOffset': 'opaque scene state'}
            app_plan = editor.plan(opaque, **dict(options, application1=57))
            self.assertEqual(set(app_plan.expected), set(OWNED))
            self.assertTrue(editor.apply(pp, app_plan, topology=topology,
                                         exclusive_project=True)['verified'])
            self.assertEqual(raw_bytes(pp, 0x21, 2), bytes((57, 202)))
            self.assertEqual(raw_text(pp, 0x70, 0x150), remote_raw)
            self.assert_unchanged(pp, before, OWNED)
            for name in OWNED:
                pp.set(name, before[name])
            case['application_change_with_opaque_advanced_state_verified'] = True
            case['six_owned_expected_fields_verified'] = True
            # Stale parameter refusal happens before a staging write or save.
            pp.set('StatusMonitorApplication', '57')
            stale_values = pp.values()
            checkpoint = len(client.commands)
            with self.assertRaises(WirelessConnectionError):
                editor.apply(pp, plan, topology=topology, exclusive_project=True)
            self.assertEqual(staged_writes(client.commands[checkpoint:]), [])
            self.assertEqual(pp.values(), stale_values)
            pp.set('StatusMonitorApplication', '56')
            case['stale_parameter_refused_without_write'] = True
            # Remote state is outside this base form's consumed snapshot.
            pp.set('RemoteIdentity8', '9 33 66 99')
            self.assertTrue(editor.apply(pp, plan, topology=topology,
                                         exclusive_project=True)['verified'])
            pp.set('RemoteIdentity8', before['RemoteIdentity8'])
            for name in OWNED:
                pp.set(name, before[name])
            case['advanced_state_not_a_base_dependency_verified'] = True
            # A fresh native project snapshot changed since planning is rejected.
            database.add(project.network, 'application', 58, 'ExtraApp')
            fresh_topology = project.topology()
            checkpoint = len(client.commands)
            with self.assertRaises(WirelessConnectionError):
                editor.apply(pp, plan, topology=fresh_topology, exclusive_project=True)
            self.assertEqual(staged_writes(client.commands[checkpoint:]), [])
            self.assertEqual(pp.values(), before)
            case['stale_topology_refused_without_write'] = True
            options['topology'] = fresh_topology
            plan = editor.plan(pp.values(), **options)
            checkpoint = len(client.commands)
            result = editor.apply(pp, plan, topology=fresh_topology, exclusive_project=True)
            self.assertTrue(result['verified'])
            self.assertFalse(any(command.upper().startswith(('PP SAVE ', 'PP SAVE_TO_SOURCE '))
                                 for command in client.commands[checkpoint:]))
            self.assertEqual(raw_bytes(pp, 0x21, 2), bytes((56, 202)))
            self.assertEqual(raw_bytes(pp, 0x37, 1), bytes((57,)))
            self.assertEqual(raw_bytes(pp, 0x41, 1)[0] & 0x0F, 15)
            self.assertEqual(raw_bytes(pp, 0x42, 7), bytes((27, 123, 99, 255, 255, 255, 255)))
            self.assertEqual(raw_text(pp, 0x70, 0x150), remote_raw)
            case['raw_byte_assertions'] += 11
            case['unrelated_parameters_preserved'] = self.assert_unchanged(pp, before, OWNED)
            case['staged_verified'] = True
            # Native accepts a complete seven-byte cleared route. This is
            # explicit normalized database evidence, not a claim about the
            # original form's uncertain six-value route save string.
            clear_plan = editor.plan(pp.values(), **dict(options, destination_network=None, adjacent_network=False,
                                                        synchronise_to_wired=False))
            self.assertTrue(editor.apply(pp, clear_plan, topology=fresh_topology, exclusive_project=True)['verified'])
            self.assertEqual(raw_bytes(pp, 0x42, 7), bytes((255, 255, 255, 255, 255, 255, 255)))
            self.assertEqual(raw_bytes(pp, 0x41, 1)[0] & 0x0F, 8)
            self.assertEqual(raw_text(pp, 0x70, 0x150), remote_raw)
            self.assert_unchanged(pp, before, OWNED)
            case['disabled_route_raw_hex'] = 'FFFFFFFFFFFFFF'
            case['disabled_route_native_normalized_seven_bytes'] = True
            case['raw_byte_assertions'] += 8
            restored_plan = editor.plan(pp.values(), **options)
            self.assertTrue(editor.apply(pp, restored_plan, topology=fresh_topology, exclusive_project=True)['verified'])
            self.assertEqual(raw_bytes(pp, 0x42, 7), bytes((27, 123, 99, 255, 255, 255, 255)))
            self.assertEqual(pp.values()['MapWirelessRemotes'], '1')
            self.assertEqual(raw_bytes(pp, 0x41, 1)[0] & 0x0F, 15)
            case['base_connection_visible_with_remote_mode_bit_preserved'] = True
            values, raw = pp.values(), raw_text(pp, 0x20, 0x1A0)
            checkpoint = len(client.commands)
            pp.save_to_source()
            self.assertEqual(sum(command.startswith('PP SAVE_TO_SOURCE ')
                                 for command in client.commands[checkpoint:]), 1)
            case['pp_save_to_source_confirmed'] = True
        client.command('PROJECT SAVE ' + project.name)
        client.command('PROJECT CLOSE ' + project.name)
        client.command('PROJECT LOAD ' + project.name)
        client.command('PROJECT USE ' + project.name)
        with Programmer(client).load(project.network, project.path) as pp:
            self.assertEqual(pp.values(), values)
            self.assertEqual(raw_text(pp, 0x20, 0x1A0), raw)
            self.assertEqual(raw_text(pp, 0x70, 0x150), remote_raw)
        self.assert_closed(client, project)
        case['all_four_networks_closed_before_and_after_reload'] = True
        case['save_close_reload_passed'] = True
        return case

    def exercise_cli(self, client, project):
        """Run the actual command entrypoint in fresh processes against owned PP data."""
        from cbus_toolkit.wireless_connection import OWNED
        database = NativeDatabase(client)
        database.create_unit(project.network, 200, 'Gateway', 'WGATE5N', '2.4.99', catalog_number='5800WCGA')
        with Programmer(client).load(project.network, project.path) as pp:
            self.seed(pp)
            pp.save_to_source()
            before, before_raw = pp.values(), raw_text(pp, 0x20, 0x1A0)
            snapshot = pp.export_parameters()
        client.command('PROJECT SAVE ' + project.name)
        project_xml = xml_text(database.get('//' + project.name, xml=True)).encode()
        self.assert_closed(client, project)
        root = Path(__file__).resolve().parents[1]
        environment = dict(os.environ, PYTHONPATH=os.pathsep.join(map(str, (root / 'src', root, root / 'tests'))))

        def invoke(arguments, status=0):
            completed = subprocess.run([sys.executable, '-m', 'cbus_toolkit', *arguments],
                                       cwd=root.parent, env=environment, capture_output=True, text=True, timeout=45)
            self.assertEqual(completed.returncode, status, completed.stdout + completed.stderr)
            return json.loads(completed.stdout if status == 0 else completed.stderr)

        case = {'unit_type': 'WGATE5N', 'firmware': '2.4.99', 'catalog_number': '5800WCGA',
                'entrypoint': 'python -m cbus_toolkit', 'subprocess_invocations': 4,
                'complete_project_xml_bytes': len(project_xml),
                'complete_project_xml_sha256': hashlib.sha256(project_xml).hexdigest(),
                'complete_parameter_snapshot_count': len(before), 'physical_hardware_verified': False}
        with TemporaryDirectory(prefix='cbus-wireless-base-connection-cli-') as work:
            directory = Path(work)
            xml_path, snapshot_path, plan_path = (directory / name for name in ('project.xml', 'snapshot.json', 'plan.json'))
            xml_path.write_bytes(project_xml)
            snapshot_path.write_text(json.dumps(snapshot))
            document = invoke(['wireless', 'connection', 'plan', str(snapshot_path),
                               '--project-xml', str(xml_path), '--source-network', '254', '--gateway-address', '200',
                               '--application1', '57', '--adjacent-network', 'on', '--synchronise-to-wired', 'on',
                               '--destination-network', '99', '--status-monitor-application', '57'])
            self.assertEqual(document['changes']['ForwardingRoute'], [27, 123, 99, 255, 255, 255, 255])
            self.assertEqual(set(document['expected']), set(OWNED))
            self.assertEqual(document['changes']['Application'], [57, 202])
            plan_path.write_text(json.dumps(document))
            target = ['cgate', '--host', '127.0.0.1', '--port', str(self.service.port), 'unit',
                      '--source', project.path, '--lock-address', project.network]
            operation = ['wireless-gateway', '--plan', str(plan_path), '--exclusive-project']
            dry_run = invoke([*target, '--dry-run', *operation])
            self.assertTrue(dry_run['verified'])
            self.assertFalse(dry_run['saved'])
            with Programmer(client).load(project.network, project.path) as pp:
                self.assertEqual(pp.values(), before)
                self.assertEqual(raw_text(pp, 0x20, 0x1A0), before_raw)
            case['dry_run_verified_without_persistent_change'] = True
            applied = invoke([*target, *operation])
            self.assertTrue(applied['verified'])
            self.assertTrue(applied['saved'])
            self.assertEqual(applied['destination'], project.path)
            with Programmer(client).load(project.network, project.path) as pp:
                after, after_raw = pp.values(), raw_text(pp, 0x20, 0x1A0)
                self.assertEqual(after, applied['parameters'])
                self.assertEqual(raw_bytes(pp, 0x42, 7), bytes((27, 123, 99, 255, 255, 255, 255)))
                self.assertEqual(raw_bytes(pp, 0x41, 1)[0] & 0x0F, 15)
                self.assertEqual(raw_bytes(pp, 0x37, 1), bytes((57,)))
                self.assertEqual(raw_bytes(pp, 0x21, 2), bytes((57, 202)))
                self.assertEqual(raw_text(pp, 0x70, 0x150), before_raw[(0x70-0x20)*2:(0x1C0-0x20)*2])
                case['unrelated_parameters_preserved'] = self.assert_unchanged(pp, before, OWNED)
            case['saved_and_fresh_pp_readback_verified'] = True
            refused = invoke([*target, *operation], status=1)
            self.assertIn('changed since', json.dumps(refused))
            with Programmer(client).load(project.network, project.path) as pp:
                self.assertEqual(pp.values(), after)
                self.assertEqual(raw_text(pp, 0x20, 0x1A0), after_raw)
            case['stale_plan_refused_without_persistent_change'] = True
        for action in ('SAVE', 'CLOSE', 'LOAD', 'USE'):
            client.command(f'PROJECT {action} {project.name}')
        with Programmer(client).load(project.network, project.path) as pp:
            self.assertEqual(pp.values(), after)
            self.assertEqual(raw_text(pp, 0x20, 0x1A0), after_raw)
        self.assert_closed(client, project)
        case['save_close_reload_passed'] = True
        case['all_four_networks_closed_and_idle_before_and_after'] = True
        return case

    def test_plan_stale_apply_raw_readback_and_save_close_reload(self):
        report = {'format': 'cbus-wireless-base-connection-native-acceptance-v1', 'backend': 'local',
                  'scope': 'Owned native C-Gate closed synthetic database project; no radio or physical network',
                  'executed_test_id': ('tests/test_wireless_base_connection_native.py::WirelessBaseConnectionNativeTest::'
                                       'test_plan_stale_apply_raw_readback_and_save_close_reload'),
                  'original_toolkit_gui_executed': False,
                  'types': [], 'physical_hardware_verified': False, 'passed': False}
        root = Path(__file__).resolve().parents[1]
        report['source_sha256'] = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in (
            'src/cbus_toolkit/wireless_connection.py', 'src/cbus_toolkit/wireless_gateway.py',
            'src/cbus_toolkit/wireless_cli.py', 'src/cbus_toolkit/cli.py',
            'tests/test_wireless_base_connection_native.py')}
        with ClosedDatabaseClient('127.0.0.1', self.service.port, timeout=30) as client:
            report['greeting'] = client.greeting
            for firmware, catalog in (('2.2.90', '5800WCGA'), ('2.4.99', 'SLC5800WCGD')):
                with self.subTest(firmware=firmware), ClosedProject(client) as project:
                    report['types'].append(self.exercise(client, project, firmware, catalog))
            with ClosedProject(client) as project:
                report['native_cli'] = self.exercise_cli(client, project)
            self.assertFalse(any(command.upper().startswith('NET OPEN') for command in client.commands))
            self.assertFalse(any(command.upper().startswith(('NET SYNC ', 'DO '))
                                 for command in client.commands))
            report['network_sync_commands'] = 0
            report['application_control_commands'] = 0
            report['network_open_commands'] = 0
            report['network_open_command_audit_scope'] = ('In-process harness commands; CLI subprocesses use exact '
                                                         '/db sources with closed/idle checks before and after')
        report['service'] = {name: self.service.report[name] for name in (
            'vendor_jar_sha256', 'java_version', 'listener_ownership_verified', 'projects_adopted')}
        self.service.close()
        for name in ('cleanup_complete', 'process_exit_confirmed', 'work_removed'):
            self.assertTrue(self.service.report[name])
            report['service'][name] = self.service.report[name]
        report['passed'] = (len(report['types']) == 2 and all(row['save_close_reload_passed'] for row in report['types'])
                            and report['native_cli']['save_close_reload_passed'])
        self.assertTrue(report['passed'])
        if os.environ.get('CBUS_WIRELESS_BASE_CONNECTION_REPORT'):
            Path(os.environ['CBUS_WIRELESS_BASE_CONNECTION_REPORT']).write_text(json.dumps(report, indent=2) + '\n')


class WirelessBaseConnectionReceiptTest(unittest.TestCase):
    def test_retained_positive_native_evidence_and_physical_boundary(self):
        root = Path(__file__).resolve().parents[1]
        receipt = json.loads((root / 'research/fixtures/wireless-base-connection-native-acceptance.json').read_text())
        self.assertTrue(receipt['passed'])
        self.assertFalse(receipt['physical_hardware_verified'])
        self.assertFalse(receipt['original_toolkit_gui_executed'])
        self.assertEqual(receipt['network_open_commands'], 0)
        self.assertEqual(receipt['network_sync_commands'], 0)
        self.assertEqual(receipt['application_control_commands'], 0)
        self.assertEqual([(row['unit_type'], row['firmware']) for row in receipt['types']],
                         [('WGATE5N', '2.2.90'), ('WGATE5N', '2.4.99')])
        expected_sources = {'src/cbus_toolkit/wireless_connection.py',
                            'src/cbus_toolkit/wireless_gateway.py',
                            'src/cbus_toolkit/wireless_cli.py', 'src/cbus_toolkit/cli.py',
                            'tests/test_wireless_base_connection_native.py'}
        self.assertEqual(set(receipt['source_sha256']), expected_sources)
        # The receipt predates the merged firmware CLI change. Verify its exact
        # executed source rather than relabeling its hashes as current evidence.
        historical = root / 'research/fixtures/wireless-base-connection-native-source.zip'
        self.assertEqual(hashlib.sha256(historical.read_bytes()).hexdigest(),
                         '8e7c0c6e347790c57d82a2dd7984b4c42537c876b5a999c6aeb0eaaa67b0f40b')
        with zipfile.ZipFile(historical) as archive:
            self.assertEqual(set(archive.namelist()), expected_sources)
            for name, digest in receipt['source_sha256'].items():
                self.assertLessEqual(archive.getinfo(name).file_size, 1024 * 1024)
                self.assertEqual(digest, hashlib.sha256(archive.read(name)).hexdigest(), name)
                if name not in ('src/cbus_toolkit/cli.py', 'tests/test_wireless_base_connection_native.py'):
                    self.assertEqual(digest, hashlib.sha256((root / name).read_bytes()).hexdigest(), name)
        for row in receipt['types']:
            for name in ('staged_verified', 'stale_parameter_refused_without_write',
                         'stale_topology_refused_without_write', 'save_close_reload_passed',
                         'all_four_networks_closed_before_and_after_reload',
                         'application_change_with_opaque_advanced_state_verified',
                         'six_owned_expected_fields_verified',
                         'advanced_state_not_a_base_dependency_verified',
                         'base_connection_visible_with_remote_mode_bit_preserved'):
                self.assertTrue(row[name], name)
            self.assertGreater(row['unrelated_parameters_preserved'], 32)
        for name in ('listener_ownership_verified', 'cleanup_complete', 'process_exit_confirmed', 'work_removed'):
            self.assertTrue(receipt['service'][name], name)
        self.assertFalse(receipt['service']['projects_adopted'])
        for name in ('dry_run_verified_without_persistent_change', 'saved_and_fresh_pp_readback_verified',
                     'stale_plan_refused_without_persistent_change', 'save_close_reload_passed',
                     'all_four_networks_closed_and_idle_before_and_after'):
            self.assertTrue(receipt['native_cli'][name], name)


if __name__ == '__main__':
    unittest.main()
