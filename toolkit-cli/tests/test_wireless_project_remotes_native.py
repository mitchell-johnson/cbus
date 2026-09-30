"""Owned native WTXU metadata acceptance, with closed synthetic projects only.

Select CBUS_NATIVE_SERVICE_BACKEND=local plus CBUS_LOCAL_CGATE_VENDOR,
CBUS_CGATE_JAVA and CBUS_UNITSPEC_DIR explicitly. No PP initialization, gateway
programming, radio action or existing native service belongs to this workflow.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4
from xml.etree import ElementTree as ET

from cbus_toolkit.native import NativeDatabase
from cbus_toolkit.programming import Programmer, xml_text
from test_wireless_connection_native import ClosedDatabaseClient, ENABLED, raw_text


EXPECTED_DEFAULTS = {
    'UnitAddress': '0xff', 'Application': '0xff 0xff', 'Project': 'CLIPSAL ',
    'NetworkAddress': '0xff', 'UnitName': 'NEWUNIT ', 'SerialNo': '0x0 0x0 0x0 0x0',
    'CustType': '0xff 0xff 0xff 0xff 0xff 0xff 0xff 0xff',
}


def elements(document):
    return {child.tag: child.text or '' for child in ET.fromstring(document) if child.tag != 'PP'}


def native_config(document):
    root = ET.fromstring(document)
    if root.tag != 'Project':
        root = root.find('Project')
    if root is None:
        raise AssertionError('Expected native project XML')
    matches = [node for node in root.findall('Config') if node.findtext('Application') == 'cgate']
    if len(matches) != 1:
        raise AssertionError('Owned native project must have exactly one cgate configuration')
    config = matches[0]
    identities = []
    for node in [config, *config.findall('Property')]:
        identities.append(node.findtext('OID'))
        node.remove(node.find('OID'))
    return identities, ET.tostring(config)


def mutations(commands):
    return [command for command in commands if command.upper().startswith(
        ('DBADD', 'DBSET', 'DBDELETE', 'PP SET', 'PP RESET', 'PP SAVE', 'PROJECT SAVE'))]


class RemoteProject:
    def __init__(self, client):
        self.client = client
        self.name = 'WR' + uuid4().hex[:6].upper()
        self.network = f'//{self.name}/254'
        self.gateway = self.network + '/p/200'

    def __enter__(self):
        self.client.command('PROJECT NEW ' + self.name)
        self.client.command('PROJECT USE ' + self.name)
        db = NativeDatabase(self.client)
        db.create_network(self.name, 254, 'Synthetic', 'Cni', '127.0.0.1:29999')
        db.create_unit(self.network, 200, 'Gateway', 'WGATE5F', '2.4.00', catalog_number='5800WCGA')
        # Distinct values across mappings and scene storage expose unintended
        # gateway PP normalization or a blanket reset during remote creation.
        with Programmer(self.client).load(self.network, '/db' + self.gateway) as pp:
            pp.set('MapWirelessRemotes', '1')
            pp.set('RemoteIdentity2', '239 205 171 153')
            pp.set('GroupAddress2', '19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34')
            pp.set('ApplicationSeconday2', '0 1 0 1 0 1 0 1 0 1 0 1 0 1 0 1')
            pp.set('SceneTriggerGroup', '100 101 102 103 104 105 106 107')
            pp.set('SceneTriggerLevel', '8 7 6 5 4 3 2 1')
            pp.save_to_source()
            self.gateway_values = pp.values()
            self.gateway_raw = raw_text(pp, 0x20, 0x1A0)
        self.client.command('PROJECT SAVE ' + self.name)
        self.assert_closed()
        return self

    def __exit__(self, *_):
        self.client.command('PROJECT CLOSE ' + self.name)

    def assert_closed(self):
        for field, value in (('InterfaceState', 'closed'), ('TargetInterfaceState', 'closed'), ('SyncState', 'idle')):
            reply = self.client.command(f'GET {self.network} {field}')
            if not any(f'{field}={value}'.lower() in line.lower() for line in reply.lines):
                raise AssertionError(reply.lines)

    def snapshot(self):
        return xml_text(NativeDatabase(self.client).get('//' + self.name, xml=True)).encode()

    def reload(self):
        for action in ('CLOSE', 'LOAD', 'USE'):
            self.client.command(f'PROJECT {action} {self.name}')
        self.assert_closed()

    def add_metadata_unit(self, address, name, *, serial=None):
        db = NativeDatabase(self.client)
        db.add(self.network, 'unit', address, name)
        path = f'{self.network}/p/{address}'
        for field, value in (('UnitType', 'WTXU'), ('UnitName', 'REMOTE'), ('FirmwareVersion', '0')):
            db.set(path + '/' + field, value)
        if serial is not None:
            db.set(path + '/SerialNumber', serial)
        return path


class ObservedSaves:
    """Read each confirmed native save, optionally lose its reply afterward.

    This injects uncertainty in the caller after the real native save; it does
    not claim to simulate a transport interruption inside vendor persistence.
    """
    def __init__(self, client, project, address, *, uncertain_save=None):
        self.client, self.project, self.address = client, project, address
        self.uncertain_save = uncertain_save
        self.commands, self.saved_rows, self.config_observations = [], [], []
        self.previous_config = native_config(project.snapshot())

    def command(self, command):
        self.commands.append(command)
        result = self.client.command(command)
        if command.upper().startswith('PROJECT SAVE '):
            row = xml_text(NativeDatabase(self.client).get(f'{self.project.network}/p/{self.address}', xml=True))
            self.saved_rows.append(elements(row))
            current = native_config(self.project.snapshot())
            if current[1] != self.previous_config[1]:
                raise AssertionError('Native save changed configuration values or structure')
            self.config_observations.append(sum(first != second for first, second in
                                               zip(self.previous_config[0], current[0], strict=True)))
            self.previous_config = current
            if len(self.saved_rows) == self.uncertain_save:
                raise OSError('Injected loss of confirmed native save response')
        return result


@unittest.skipUnless(ENABLED, 'Select an owned local native C-Gate and decoded specs for WTXU acceptance')
class WirelessProjectRemotesNativeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from research.local_cgate import LocalCGate
        cls.service = LocalCGate(os.environ['CBUS_LOCAL_CGATE_VENDOR'])
        cls.addClassCleanup(cls.service.close)
        (cls.service.work / 'config/access.txt').write_text('interface 127.0.0.1 Clipsal\n')
        cls.service.start()

    def assert_gateway_preserved(self, client, project):
        with Programmer(client).load(project.network, '/db' + project.gateway) as pp:
            self.assertEqual(pp.values(), project.gateway_values)
            self.assertEqual(raw_text(pp, 0x20, 0x1A0), project.gateway_raw)
        return len(project.gateway_values)

    def exercise_cli(self, client, project):
        """Run the real CLI in fresh processes against the owned closed server."""
        root = Path(__file__).resolve().parents[1]
        environment = dict(os.environ, PYTHONPATH=os.pathsep.join(map(str, (root / 'src', root, root / 'tests'))))
        # Metadata creation must not depend on decoded programming specs.
        environment.pop('CBUS_UNITSPEC_DIR', None)
        catalogue = Path(os.environ['CBUS_LOCAL_CGATE_VENDOR']) / 'unitspec/cbusunits.xml'
        before_xml = project.snapshot()
        case = {'entrypoint': 'python -m cbus_toolkit', 'subprocess_invocations': 4,
                'decoded_unit_specification_available': False, 'physical_hardware_verified': False}

        def invoke(arguments, status=0):
            result = subprocess.run([sys.executable, '-m', 'cbus_toolkit', *arguments],
                                    cwd=root.parent, env=environment, capture_output=True, text=True, timeout=45)
            self.assertEqual(result.returncode, status, result.stdout + result.stderr)
            return json.loads(result.stdout if status == 0 else result.stderr)

        with TemporaryDirectory(prefix='cbus-wireless-project-remote-cli-') as work:
            directory = Path(work)
            xml_path, plan_path = directory / 'project.xml', directory / 'plan.json'
            xml_path.write_bytes(before_xml)
            plan = invoke(['wireless', 'project-remote', 'plan', '--project-xml', str(xml_path),
                           '--catalogue-xml', str(catalogue), '--source-network', '254',
                           '--gateway-address', '200', '--serial', '70179.836'])
            plan_path.write_text(json.dumps(plan))
            target = ['cgate', '--host', '127.0.0.1', '--port', str(self.service.port), 'unit',
                      '--source', '/db' + project.gateway, '--lock-address', project.network]
            operation = ['wireless-gateway', '--plan', str(plan_path), '--exclusive-project']
            preview = invoke([*target, '--dry-run', *operation])
            self.assertTrue(preview['preflight_verified'])
            self.assertFalse(preview['saved'])
            self.assertFalse(preview['pp_initialized'])
            self.assertEqual(project.snapshot(), before_xml)
            self.assert_gateway_preserved(client, project)
            case['dry_run_verified_without_project_mutation'] = True
            result = invoke([*target, *operation])
            self.assertTrue(result['saved'])
            self.assertTrue(result['preserved_existing_project'])
            self.assertEqual(result['created_address'], 100)
            self.assertEqual([row['completed'] for row in result['project_save_attempts']], [True, True, True])
            self.assertFalse(result['pp_initialized'])
            self.assertFalse(result['gateway_mappings_changed'])
            case['project_save_stages'] = [row['stage'] for row in result['project_save_attempts']]
            case['gateway_parameters_preserved'] = self.assert_gateway_preserved(client, project)
            remote = project.network + '/p/100'
            xml = xml_text(NativeDatabase(client).get(remote, xml=True))
            row = elements(xml)
            self.assertEqual(result['created_oid'], row['OID'])
            self.assertEqual(row['SerialNumber'], '70179.836')
            self.assertEqual(row['TagName'], 'Remote 01')
            self.assertEqual(ET.fromstring(xml).findall('PP'), [])
            after_xml = project.snapshot()
            refusal = invoke([*target, *operation], status=1)
            self.assertIn('changed since', json.dumps(refusal))
            self.assertEqual(project.snapshot(), after_xml)
            case['stale_plan_refused_without_project_mutation'] = True
        project.reload()
        reloaded = elements(xml_text(NativeDatabase(client).get(remote, xml=True)))
        for field, value in row.items():
            self.assertEqual(reloaded[field], value)
        self.assert_gateway_preserved(client, project)
        case['save_close_reload_passed'] = True
        case['network_closed_and_idle_before_and_after'] = True
        return case

    def test_owned_metadata_creation_save_boundaries_and_preservation(self):
        from cbus_toolkit.wireless_project_remotes import (
            FrozenRemoteProject, RemoteCatalogue, RemoteCreationPlan, RemoteCreationError, RemoteCreationApplyError,
            plan_project_remote, apply_project_remote,
        )
        vendor = Path(os.environ['CBUS_LOCAL_CGATE_VENDOR'])
        catalogue_bytes = (vendor / 'unitspec/cbusunits.xml').read_bytes()
        catalogue = RemoteCatalogue.from_xml(catalogue_bytes)
        report = {
            'format': 'cbus-wireless-project-remotes-native-acceptance-v1',
            'scope': 'Owned native C-Gate closed synthetic database projects only',
            'original_toolkit_gui_executed': False, 'physical_pairing_verified': False,
            'physical_hardware_verified': False, 'passed': False,
            'catalogue_sha256': hashlib.sha256(catalogue_bytes).hexdigest(),
            'spec_sha256': hashlib.sha256((Path(os.environ['CBUS_UNITSPEC_DIR']) / 'WTXU.xml').read_bytes()).hexdigest(),
            'uncertain_saves': [],
        }
        root = Path(__file__).resolve().parents[1]
        report['source_sha256'] = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in (
            'src/cbus_toolkit/wireless_project_remotes.py', 'src/cbus_toolkit/wireless_cli.py',
            'src/cbus_toolkit/cli.py', 'tests/test_wireless_project_remotes_native.py',
        )}
        with ClosedDatabaseClient('127.0.0.1', self.service.port, timeout=30) as client:
            report['greeting'] = client.greeting
            with RemoteProject(client) as project:
                # Native allocation must fill address101 and nameRemote02,
                # independently of insertion order and neighboring occupied slots.
                project.add_metadata_unit(102, 'Remote 03')
                project.add_metadata_unit(100, 'Remote 01')
                snapshot = FrozenRemoteProject.from_xml(project.snapshot())
                before = len(client.commands)
                plan = plan_project_remote(snapshot, source_network=254, gateway_address=200,
                                           serial='70179.836', catalogue=catalogue)
                self.assertEqual(client.commands[before:], [])
                plan = RemoteCreationPlan.from_dict(json.loads(json.dumps(plan.as_dict())))
                observer = ObservedSaves(client, project, 101)
                result = apply_project_remote(observer, plan, exclusive_project=True)
                self.assertEqual(len(observer.saved_rows), 3)
                self.assertTrue(all(count > 0 for count in observer.config_observations))
                first, second, third = observer.saved_rows
                self.assertEqual(result['created_oid'], first['OID'])
                self.assertEqual(first['Address'], '101')
                self.assertEqual(first['TagName'], 'Remote 02')
                self.assertEqual(first['UnitType'], 'WTXU')
                self.assertEqual(first['UnitName'], 'REMOTE')
                self.assertEqual(first['FirmwareVersion'], '0')
                for name in ('SerialNumber', 'CatalogNumber', 'Description'):
                    self.assertNotIn(name, first)
                self.assertEqual(second['SerialNumber'], '70179.836')
                self.assertEqual(second['Description'], '')
                self.assertEqual(second['CatalogNumber'], '5888TXBA')
                self.assertEqual(second, third)
                writes = mutations(observer.commands)
                self.assertFalse(any(command.startswith('PP ') for command in writes))
                report['success'] = {'address': 101, 'tag_name': 'Remote 02', 'save_count': 3,
                                     'first_metadata_fields': sorted(first), 'final_metadata_fields': sorted(third),
                                     'remote_pp_mutations': 0, 'result': result,
                                     'native_config_oids_regenerated_per_save': observer.config_observations,
                                     'native_config_values_and_order_preserved': True}
                report['success']['gateway_parameters_preserved'] = self.assert_gateway_preserved(client, project)
                remote = f'{project.network}/p/101'
                database = NativeDatabase(client)
                before_xml = xml_text(database.get(remote, xml=True))
                self.assertEqual(ET.fromstring(before_xml).findall('PP'), [])
                with Programmer(client).load(project.network, '/db' + remote) as pp:
                    self.assertEqual(pp.values(), EXPECTED_DEFAULTS)
                    self.assertEqual(raw_text(pp, 0x20, 3), 'ffffff')
                    self.assertEqual(raw_text(pp, 0xF3, 12), '00000000ffffffffffffffff')
                self.assertEqual(xml_text(database.get(remote, xml=True)), before_xml)
                report['effective_pp_defaults'] = EXPECTED_DEFAULTS
                report['read_only_pp_load_left_metadata_unchanged'] = True
                project.reload()
                after = elements(xml_text(database.get(remote, xml=True)))
                for field, value in third.items():
                    self.assertEqual(after[field], value)
                self.assertEqual(ET.fromstring(xml_text(database.get(remote, xml=True))).findall('PP'), [])
                self.assert_gateway_preserved(client, project)
                report['success']['save_close_reload_passed'] = True
                before = len(client.commands)
                with self.assertRaises(RemoteCreationError):
                    apply_project_remote(client, plan, exclusive_project=True)
                self.assertEqual(mutations(client.commands[before:]), [])
                report['stale_plan_refused_before_mutation'] = True
                before = len(client.commands)
                with self.assertRaises(ValueError):
                    plan_project_remote(FrozenRemoteProject.from_xml(project.snapshot()), source_network=254,
                                        gateway_address=200, serial='70179.836', catalogue=catalogue)
                self.assertEqual(mutations(client.commands[before:]), [])
                report['duplicate_serial_refused_before_mutation'] = True
                negative_base = project.snapshot()
                negative_cases = []
                for kind in ('duplicate_address', 'duplicate_name', 'duplicate_identity', 'address_exhaustion'):
                    tree = ET.fromstring(negative_base)
                    network = tree.find('Network') if tree.tag == 'Project' else tree.find('Project/Network')
                    self.assertIsNotNone(network)
                    if kind == 'address_exhaustion':
                        occupied = {int(unit.findtext('Address')) for unit in network.findall('Unit')}
                        for address in range(100, 256):
                            if address in occupied:
                                continue
                            unit = ET.SubElement(network, 'Unit')
                            for field, value in (('OID', str(uuid4())), ('TagName', f'Occupied {address}'),
                                                 ('Address', str(address)), ('UnitType', 'WTXU'),
                                                 ('UnitName', 'REMOTE'), ('FirmwareVersion', '0')):
                                ET.SubElement(unit, field).text = value
                    else:
                        unit = ET.SubElement(network, 'Unit')
                        for field, value in (('OID', str(uuid4())),
                                             ('TagName', 'Remote 01' if kind == 'duplicate_name' else 'Other remote'),
                                             ('Address', '100' if kind == 'duplicate_address' else '103'),
                                             ('UnitType', 'WTXU'), ('UnitName', 'REMOTE'), ('FirmwareVersion', '0')):
                            ET.SubElement(unit, field).text = value
                        if kind == 'duplicate_identity':
                            ET.SubElement(unit, 'SerialNumber').text = '70179.836'
                    before = len(client.commands)
                    with self.assertRaises(ValueError, msg=kind):
                        malformed = FrozenRemoteProject.from_xml(ET.tostring(tree))
                        plan_project_remote(malformed, source_network=254, gateway_address=200,
                                            serial='74565.1656', catalogue=catalogue)
                    self.assertEqual(client.commands[before:], [])
                    negative_cases.append(kind)
                report['native_derived_frozen_xml_refusals_before_io'] = negative_cases
            # Each uncertainty case uses a fresh project; real native SAVE is
            # executed once and its acknowledgement is withheld from the caller.
            for boundary in (1, 2, 3):
                with RemoteProject(client) as project:
                    plan = plan_project_remote(FrozenRemoteProject.from_xml(project.snapshot()), source_network=254,
                                               gateway_address=200, serial='70179.836', catalogue=catalogue)
                    observer = ObservedSaves(client, project, 100, uncertain_save=boundary)
                    with self.assertRaises(RemoteCreationApplyError) as failure:
                        apply_project_remote(observer, plan, exclusive_project=True)
                    details = failure.exception.details
                    self.assertTrue(details['uncertain_save'])
                    self.assertEqual(len(details['project_save_attempts']), boundary)
                    self.assertFalse(details['retry_performed'])
                    self.assertFalse(details['rollback_performed'])
                    self.assertFalse(details['saved'])
                    self.assertEqual([row['completed'] for row in details['project_save_attempts']],
                                     [True] * (boundary - 1) + [False])
                    self.assertEqual(len(observer.saved_rows), boundary)
                    self.assertEqual(observer.commands[-1], 'PROJECT SAVE ' + project.name)
                    self.assert_gateway_preserved(client, project)
                    project.reload()
                    row = elements(xml_text(NativeDatabase(client).get(project.network + '/p/100', xml=True)))
                    self.assertEqual(row['TagName'], 'Remote 01')
                    self.assertEqual('SerialNumber' in row, boundary > 1)
                    if boundary > 1:
                        self.assertEqual(row['SerialNumber'], '70179.836')
                    self.assert_gateway_preserved(client, project)
                    report['uncertain_saves'].append({'boundary': boundary, 'save_attempts': boundary,
                        'later_commands': 0, 'replay_attempts': 0, 'save_close_reload_passed': True,
                        'gateway_mapping_preserved': True, 'failure_receipt': details,
                        'injection': 'Native save executed; caller acknowledgement withheld afterward'})
            with RemoteProject(client) as project:
                report['native_cli'] = self.exercise_cli(client, project)
            report['network_open_command_audit_scope'] = ('In-process harness commands; CLI subprocesses use exact '
                '/db sources with closed/idle checks before and after')
            report['network_open_commands'] = sum(command.upper().startswith('NET OPEN') for command in client.commands)
            self.assertEqual(report['network_open_commands'], 0)
        report['service'] = {name: self.service.report[name] for name in (
            'vendor_jar_sha256', 'java_version', 'listener_ownership_verified', 'projects_adopted')}
        self.service.close()
        for name in ('cleanup_complete', 'process_exit_confirmed', 'work_removed'):
            self.assertTrue(self.service.report[name])
            report['service'][name] = self.service.report[name]
        report['passed'] = True
        if os.environ.get('CBUS_WIRELESS_PROJECT_REMOTES_REPORT'):
            Path(os.environ['CBUS_WIRELESS_PROJECT_REMOTES_REPORT']).write_text(json.dumps(report, indent=2) + '\n')


class WirelessProjectRemotesReceiptTest(unittest.TestCase):
    def test_retained_native_metadata_evidence_and_physical_boundary(self):
        path = Path(__file__).resolve().parents[1] / 'research/fixtures/wireless-project-remotes-native-acceptance.json'
        receipt = json.loads(path.read_text())
        self.assertTrue(receipt['passed'])
        self.assertFalse(receipt['original_toolkit_gui_executed'])
        self.assertFalse(receipt['physical_hardware_verified'])
        self.assertFalse(receipt['physical_pairing_verified'])
        self.assertEqual(receipt['network_open_commands'], 0)
        self.assertEqual(receipt['success']['save_count'], 3)
        self.assertTrue(receipt['success']['save_close_reload_passed'])
        self.assertEqual(receipt['effective_pp_defaults'], EXPECTED_DEFAULTS)
        self.assertEqual([row['boundary'] for row in receipt['uncertain_saves']], [1, 2, 3])
        for row in receipt['uncertain_saves']:
            self.assertEqual(row['save_attempts'], row['boundary'])
            self.assertEqual(row['later_commands'], 0)
            self.assertEqual(row['replay_attempts'], 0)
            self.assertTrue(row['save_close_reload_passed'])
        for field in ('listener_ownership_verified', 'cleanup_complete', 'process_exit_confirmed', 'work_removed'):
            self.assertTrue(receipt['service'][field])
        self.assertFalse(receipt['service']['projects_adopted'])
        for field in ('dry_run_verified_without_project_mutation', 'stale_plan_refused_without_project_mutation',
                      'save_close_reload_passed', 'network_closed_and_idle_before_and_after'):
            self.assertTrue(receipt['native_cli'][field])
        self.assertFalse(receipt['native_cli']['decoded_unit_specification_available'])
        self.assertEqual(receipt['native_cli']['project_save_stages'],
                         ['constructor', 'database_agent', 'creation_caller'])


if __name__ == '__main__':
    unittest.main()
