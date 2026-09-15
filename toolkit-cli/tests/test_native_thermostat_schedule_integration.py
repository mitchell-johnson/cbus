"""Scheduling against an owned C-Gate with independent XML observations."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import unittest
from uuid import uuid4
from xml.etree import ElementTree as ET

import cbus_toolkit
from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.native import NativeDatabase, NativeProjects
from cbus_toolkit.native_thermostat_schedule import NativeScheduleError, NativeThermostatScheduleLevels
from cbus_toolkit.programming import xml_text


def name(prefix):
    return prefix + uuid4().hex[:7].upper()


def labels(action):
    # Independent bit-to-name specification, not the production formatter.
    return {n: 'Sched ' + action + (' Zone:' if n in (1, 2, 4, 8, 16) else ' Zones:')
            + ','.join(label for bit, label in ((1, 'unsw'), (2, '1'), (4, '2'), (8, '3'), (16, '4')) if n & bit)
            for n in range(1, 32)}


def records(text):
    root = ET.fromstring(text)
    if root.tag != 'NetVar':
        raise AssertionError('Native NetVar XML expected')
    rows = {}
    for node in root.findall('Level'):
        address = int(node.findtext('Address'))
        if address in rows:
            raise AssertionError('Duplicate native address')
        rows[address] = {'value': int(node.attrib['Value']), 'tag': node.findtext('TagName'),
                         'oid': node.findtext('OID')}
    return root.findtext('OID'), root.findtext('TagName'), rows


@unittest.skipUnless(os.environ.get('CBUS_CGATE_JAVA') and os.environ.get('CBUS_LOCAL_CGATE_VENDOR'),
                     'Select Java11/vendor for isolated native scheduling acceptance')
class NativeScheduleIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from research.local_cgate import LocalCGate
        cls.service = LocalCGate(os.environ['CBUS_LOCAL_CGATE_VENDOR'])
        cls.addClassCleanup(cls.service.close)
        cls.evidence = {'format': 'native-scheduling-integration-v1', 'service': cls.service.report,
                        'cases': [], 'physical_devices_accessed': False, 'network_connections': []}
        cls.sentinel = socket.socket()
        cls.addClassCleanup(cls.finish)
        cls.sentinel.bind(('127.0.0.1', 0))
        cls.sentinel.listen(1)
        cls.sentinel.settimeout(0.05)
        cls.service.start()

    @classmethod
    def finish(cls):
        first = None
        try:
            cls.service.close()
        except BaseException as error:
            first = error
        try:
            try:
                connection, peer = cls.sentinel.accept()
            except socket.timeout:
                pass
            else:
                cls.evidence['network_connections'].append(list(peer))
                connection.close()
                raise AssertionError('Closed scheduling workflow connected to its CNI sentinel')
        except BaseException as error:
            if first is None:
                first = error
        finally:
            try:
                cls.sentinel.close()
            except BaseException as error:
                if first is None:
                    first = error
        cls.evidence['cleanup_passed'] = first is None and cls.service.report['cleanup_complete']
        destination = os.environ.get('CBUS_THERMOSTAT_SCHEDULE_EVIDENCE')
        if destination:
            try:
                with Path(destination).open('x', encoding='utf-8') as stream:
                    json.dump(cls.evidence, stream, indent=2)
                    stream.write('\n')
            except BaseException as error:
                if first is None:
                    first = error
        if first is not None:
            raise first

    def setUp(self):
        self.client = CGateClient('127.0.0.1', self.service.port, timeout=5)
        self.addCleanup(self.client.close)
        self.client.connect()
        self.projects = NativeProjects(self.client)
        self.database = NativeDatabase(self.client)
        self.project = name('T')
        self.projects.operation('new', self.project)
        self.network = '//' + self.project + '/254'
        self.database.create_network(self.project, 254, 'Offline', 'Cni',
                                     '127.0.0.1:' + str(self.sentinel.getsockname()[1]))
        self.database.add(self.network, 'application', 203, 'Enable Control')
        self.case = {'test': self._testMethodName, 'project': self.project, 'observations': []}
        self.evidence['cases'].append(self.case)

    def group(self, number=1, initial=None):
        self.projects.operation('use', self.project)
        path = self.network + '/203/' + str(number)
        self.database.add(self.network + '/203', 'netvar', number, 'Owned Schedule ' + str(number))
        for address, (value, tag) in (initial or {}).items():
            self.database.add(path, 'level', address, tag)
            oid = records(self.read(path))[2][address]['oid']
            self.database.set('!' + oid + '/Value', value)
        self.reload()
        return path

    def reload(self):
        for action in ('save', 'close', 'load'):
            self.projects.operation(action, self.project)

    def read(self, path):
        return xml_text(self.database.get(path, xml=True))

    def backup(self, backup, number=1):
        self.projects.operation('load', backup)
        return self.read('//' + backup + '/254/203/' + str(number))

    def test_all_three_actions_persist_and_backup_initial_group(self):
        for number, action in enumerate(('Enable', 'Disable', 'Overrd'), 1):
            with self.subTest(action=action):
                path = self.group(number)
                before = self.read(path)
                manager = NativeThermostatScheduleLevels(self.client)
                plan = manager.plan(path, action, exclusive_project=True)
                backup = name('B')
                result = manager.apply(plan, backup_project=backup).as_dict()
                self.assertTrue(result['complete'])
                self.assertTrue(result['persistence_verified'])
                self.assertFalse(result['native_collection_order_verified'])
                final = self.read(path)
                identity, tag, rows = records(final)
                self.assertEqual((identity, tag), records(before)[:2])
                self.assertEqual({n: (row['value'], row['tag']) for n, row in rows.items()},
                                 {n: (n, label) for n, label in labels(action).items()})
                self.assertEqual(len({row['oid'] for row in rows.values()}), 31)
                backup_xml = self.backup(backup, number)
                self.assertEqual(records(backup_xml)[2], {})
                self.case['observations'].append({'action': action, 'before_xml': before,
                    'result': result, 'after_xml': final, 'backup_xml': backup_xml})

    def test_existing_extra_addresses_and_second_action_noop(self):
        initial = {255: (77, 'Existing255'), 1: (205, 'Keep first'), 32: (100, 'Existing32'), 0: (200, 'Existing0')}
        path = self.group(initial=initial)
        before = self.read(path)
        manager = NativeThermostatScheduleLevels(self.client)
        plan = manager.plan(path, 'Enable', exclusive_project=True)
        self.assertEqual(plan.created_addresses, tuple(range(2, 32)))
        backup = name('B')
        result = manager.apply(plan, backup_project=backup).as_dict()
        after = self.read(path)
        rows = records(after)[2]
        self.assertEqual(set(rows), set(initial) | set(range(1, 32)))
        for address, record in records(before)[2].items():
            self.assertEqual(rows[address], record)
        backup_xml = self.backup(backup)
        self.assertEqual({n: (r['value'], r['tag']) for n, r in records(backup_xml)[2].items()}, initial)
        noop = manager.apply(manager.plan(path, 'Disable', exclusive_project=True), backup_project=backup).as_dict()
        self.assertEqual(noop['state'], 'already_present')
        self.assertFalse(noop['target_mutation_attempted'])
        self.assertFalse(noop['backup_created'])
        self.assertFalse(any(row['command'].startswith(('PROJECT ', 'DBADD', 'DBSET')) for row in noop['commands']))
        self.assertEqual(self.read(path), after)
        self.case['observations'].append({'before_xml': before, 'after_xml': after, 'backup_xml': backup_xml,
                                          'result': result, 'noop': noop})

    def test_stale_tag_refused_before_backup_or_mutation(self):
        path = self.group(initial={1: (205, 'Keep')})
        manager = NativeThermostatScheduleLevels(self.client)
        plan = manager.plan(path, 'Enable', exclusive_project=True)
        self.projects.operation('use', self.project)
        self.database.set('!' + plan.group_oid + '/TagName', 'External edit')
        current = self.read(path)
        with self.assertRaises(NativeScheduleError):
            manager.apply(plan, backup_project=name('B'))
        result = manager.last_result.as_dict()
        self.assertFalse(result['backup_created'])
        self.assertFalse(result['target_mutation_attempted'])
        self.assertFalse(any(row['command'].startswith(('PROJECT ', 'DBADD', 'DBSET')) for row in result['commands']))
        self.assertEqual(self.read(path), current)
        self.case['observations'].append({'current_xml': current, 'result': result})

    def test_cli_preview_apply_noop_and_invalid_request(self):
        path = self.group(initial={1: (205, 'Keep')})
        before = self.read(path)
        listing = self.projects.directory().lines
        command = [sys.executable, '-m', 'cbus_toolkit', 'cgate', '--host', '127.0.0.1',
                   '--port', str(self.service.port), 'thermostat-schedule-levels', path,
                   '--action', 'Overrd', '--exclusive-project']
        environment = dict(os.environ)
        environment['PYTHONPATH'] = str(Path(cbus_toolkit.__file__).resolve().parent.parent)
        def invoke(extra, expected_status=0):
            process = subprocess.run(command + extra, capture_output=True, text=True, timeout=30,
                                     env=environment, stdin=subprocess.DEVNULL)
            self.assertEqual(process.returncode, expected_status, process.stderr)
            output = json.loads(process.stdout if expected_status == 0 else process.stderr)
            self.case['observations'].append({'argv': command + extra, 'exit_status': process.returncode,
                                              'stdout': process.stdout, 'stderr': process.stderr})
            return output
        preview = invoke([])
        self.assertEqual(preview['created_addresses'], list(range(2, 32)))
        self.assertFalse(preview['native_mutation_performed'])
        self.assertTrue(preview['cli']['connection_exit_completed'])
        self.assertEqual(self.projects.directory().lines, listing)
        self.assertEqual(self.read(path), before)
        invalid = invoke(['--backup-project', name('B')], 1)
        self.assertEqual(invalid['thermostat_schedule_evidence']['phase'], 'cli_preflight')
        self.assertEqual(self.read(path), before)
        backup = name('B')
        result = invoke(['--apply', '--backup-project', backup])
        self.assertTrue(result['complete'] and result['persistence_verified'] and result['cli']['complete'])
        self.assertFalse(result['physical_device_programmed'])
        after = self.read(path)
        rows = records(after)[2]
        self.assertEqual(rows[1], records(before)[2][1])
        self.assertEqual({n: (r['value'], r['tag']) for n, r in rows.items() if n != 1},
                         {n: (n, label) for n, label in labels('Overrd').items() if n != 1})
        noop = invoke(['--apply', '--action', 'Disable', '--backup-project', backup])
        self.assertEqual(noop['state'], 'already_present')
        self.assertFalse(noop['target_mutation_attempted'])
        self.assertEqual(self.read(path), after)
        backup_xml = self.backup(backup)
        self.assertEqual({n: (r['value'], r['tag']) for n, r in records(backup_xml)[2].items()}, {1: (205, 'Keep')})
        self.case['observations'].append({'before_xml': before, 'after_xml': after, 'backup_xml': backup_xml})

    def test_lost_value_and_tag_receipts_preserve_real_partial_state(self):
        for number, field in enumerate(('Value', 'TagName'), 1):
            with self.subTest(field=field):
                path = self.group(number, {1: (205, 'Keep')})
                before = self.read(path)
                first = ConnectionError('Injected lost receipt after actual native ' + field)
                underlying = self.client
                class LostReceipt:
                    fired = False
                    def command(peer, command):
                        response = underlying.command(command)
                        if not peer.fired and command.startswith('DBSETSAFE !') and '/' + field + ' ' in command:
                            peer.fired = True
                            raise first
                        return response
                peer = LostReceipt()
                manager = NativeThermostatScheduleLevels(peer)
                backup = name('B')
                with self.assertRaises(NativeScheduleError) as caught:
                    manager.apply(manager.plan(path, 'Overrd', exclusive_project=True), backup_project=backup)
                self.assertIs(caught.exception.cause, first)
                result = manager.last_result.as_dict()
                self.assertTrue(result['backup_created'])
                self.assertTrue(result['target_mutation_attempted'])
                self.assertFalse(result['target_save_attempted'])
                self.assertFalse(result['persistence_verified'])
                self.assertEqual(len(result['levels']), 1)
                self.assertTrue(result['levels'][0]['created'])
                self.assertFalse(result['levels'][0]['tag_confirmed'])
                self.assertEqual(result['levels'][0]['value_confirmed'], field == 'TagName')
                # A new independent connection observes actual native state;
                # no retry, save or rollback is delegated to the adapter.
                with CGateClient('127.0.0.1', self.service.port, timeout=5) as observer:
                    partial = xml_text(NativeDatabase(observer).get(path, xml=True))
                rows = records(partial)[2]
                self.assertEqual(set(rows), {1, 2})
                self.assertEqual(rows[1], records(before)[2][1])
                self.assertEqual(rows[2]['value'], 2)
                self.assertEqual(rows[2]['tag'], 'Level 2' if field == 'Value' else labels('Overrd')[2])
                backup_xml = self.backup(backup, number)
                self.assertEqual({n: (r['value'], r['tag']) for n, r in records(backup_xml)[2].items()}, {1: (205, 'Keep')})
                self.case['observations'].append({'field': field, 'before_xml': before, 'partial_xml': partial,
                                                  'backup_xml': backup_xml, 'result': result})
