"""Original C-Gate consumes compiled classic broadcasts into an owned peer.

The peer independently decodes SAL packets. Its stored bitmap then ICON state
is software acceptance, not device image-cache, display or flash acceptance.
"""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from uuid import uuid4
import xml.etree.ElementTree as ET

from cbus_toolkit.dlt_broadcast import compile_broadcast, assess_broadcast
from test_macros import NATIVE, NATIVE_REASON, native_endpoint


def request(project, **changes):
    result = {'format': 'cbus-classic-dlt-broadcast-request-v1',
              'project': project, 'network': 254, 'application': 56,
              'application_oid': None, 'group': 1, 'level': None,
              'language': 1, 'variant': 1, 'tag_type': 'TEXT',
              'tag_value': 'Kitchen', 'already_broadcast': False, 'bitmap': None}
    result.update(changes)
    return result


@unittest.skipUnless(NATIVE, NATIVE_REASON)
class NativeDltBroadcastTests(unittest.TestCase):
    def test_compiled_commands_reach_owned_independent_receiver(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import xml_text
        from cbus_toolkit.simulator import PCISimulator
        from research.local_cgate import JAR_SHA256, service_backend

        # This fixture deliberately creates its own local native child rather
        # than adopting a configured remote service or physical interface.
        if service_backend() != 'local':
            self.skipTest('broadcast oracle requires the owned local C-Gate backend')
        project = 'BC' + uuid4().hex[:6].upper()
        network = f'//{project}/254'
        report = {'format': 'cbus-classic-dlt-broadcast-native-v1',
                  'cgate_jar_sha256': JAR_SHA256, 'passed': False,
                  'scope': 'Compiled commands to owned original C-Gate and independent synthetic PCI receiver',
                  'household_endpoint_used': False, 'original_toolkit_executed': False,
                  'physical_device_verified': False, 'rendering_verified': False,
                  'physical_persistence_verified': False, 'cases': []}
        with tempfile.TemporaryDirectory() as directory, native_endpoint() as (host, port):
            state_path = Path(directory) / 'synthetic-labels.json'
            simulator = PCISimulator(profile='synthetic', state_path=state_path)
            with simulator.running('127.0.0.1', 0) as (_, peer_port), \
                    CGateClient(host, port=port, timeout=30) as client:
                created = False
                loaded = False

                def eventually(predicate):
                    deadline = time.monotonic() + 5
                    while not predicate() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertTrue(predicate(), simulator.labels.snapshot())

                try:
                    client.command('PROJECT NEW ' + project)
                    created = True
                    client.command('PROJECT USE ' + project)
                    client.command(f'DBCREATENET 254 Broadcast_Oracle Cni 127.0.0.1:{peer_port}')
                    for application in (56, 202, 203):
                        client.command(f'DBADDSAFE {network} Application {application} Labels_{application}')
                    client.command('PROJECT SAVE ' + project)
                    client.command('NET LOAD DB ' + project)
                    loaded = True
                    client.command('NET OPEN ' + network)
                    deadline = time.monotonic() + 20
                    while True:
                        state = client.command('GET ' + network + ' state')
                        # Labels can be queued once the native transport is
                        # open. Complete unit discovery is a separate workflow;
                        # each label below must independently reach the peer.
                        if any('state=ok' in line or 'state=sync' in line for line in state.lines):
                            report['network_state_before_commands'] = state.final.rsplit('=', 1)[-1]
                            report['full_network_discovery_verified'] = False
                            break
                        self.assertLess(time.monotonic(), deadline,
                                        (state.lines, simulator.wire_log[-20:]))
                        time.sleep(0.1)
                    application_xml = ET.fromstring(xml_text(NativeDatabase(client).get(network + '/56', xml=True)))
                    application_oid = application_xml.findtext('OID')
                    self.assertTrue(application_oid)
                    pixels = bytes(range(128)).hex()
                    cases = [
                        ('text14', request(project, tag_value='12345678901234567890'),
                         {'kind': 'text', 'text': '12345678901234', 'data_hex': b'12345678901234'.hex()}),
                        ('latin1', request(project, group=2, variant=4, tag_value='Café'),
                         {'kind': 'text', 'text': None, 'data_hex': '436166e9'}),
                        ('default-marker', request(project, group=3, tag_value='<Default>'),
                         {'kind': 'text', 'text': '\x10', 'data_hex': '10'}),
                        ('empty-marker', request(project, group=4, tag_value=''),
                         {'kind': 'text', 'text': '\x10', 'data_hex': '10'}),
                        ('icon-oid', request(project, application_oid=application_oid, group=5,
                                             tag_type='ICON', tag_value='258', variant=2),
                         {'kind': 'icon', 'icon': 258, 'data_hex': '010102'}),
                        ('trigger-level', request(project, application=202, group=6, level=9,
                                                  language=2, variant=3, tag_value='Scene'),
                         {'kind': 'text', 'text': 'Scene', 'data_hex': '5363656e65'}),
                        ('enable', request(project, application=203, group=7, tag_value='Enable'),
                         {'kind': 'text', 'text': 'Enable', 'data_hex': '456e61626c65'}),
                        ('dynamic', request(project, group=8, tag_type='DYNAMIC', tag_value='65535',
                                            bitmap={'width': 64, 'data_hex': pixels}),
                         {'kind': 'icon', 'icon': 65535, 'data_hex': '01ffff'}),
                        ('font-prepared', request(project, group=9, tag_type='FONT',
                                                 tag_value='258,Arial,12,0,0,0,0,0,0,Font',
                                                 bitmap={'width': 64, 'data_hex': pixels}),
                         {'kind': 'icon', 'icon': 258, 'data_hex': '010102'}),
                    ]
                    for name, supplied, expected in cases:
                        plan = compile_broadcast(supplied).as_dict()
                        observations = []
                        key = (supplied['application'], supplied['group'], supplied['level'],
                               supplied['language'], supplied['variant'] - 1)
                        snapshots = []
                        for command in plan['commands']:
                            response = client.command(command['text'])
                            self.assertEqual(response.code, 200)
                            observations.append({'index': command['index'],
                                'command_sha256': command['sha256'], 'outcome': 'response',
                                'responses': list(response.lines)})
                            intermediate = expected
                            if supplied['tag_type'] in ('DYNAMIC', 'FONT') and command['index'] == 1:
                                intermediate = {'kind': 'dynamic', 'icon': int(supplied['tag_value'].split(',')[0]),
                                    'width': 64, 'height': 16, 'vertical_offset': 10, 'data_hex': pixels}
                            eventually(lambda: simulator.labels.labels.get(key) == intermediate)
                            snapshots.append(dict(simulator.labels.labels[key]))
                        assessed = assess_broadcast(plan, {
                            'format': 'cbus-classic-dlt-broadcast-outcomes-v1',
                            'plan_sha256': plan['plan_sha256'], 'attempts': observations})
                        self.assertTrue(assessed['native_accepted'])
                        self.assertTrue(assessed['original_cache_marked'])
                        self.assertFalse(assessed['device_verified'])
                        self.assertFalse(assessed['io_performed'])
                        report['cases'].append({'name': name, 'commands': [
                            command['text'].replace(project, 'ORACLE').replace(application_oid, 'APPLICATION_OID')
                            for command in plan['commands']],
                            'response_lines': [row['responses'] for row in observations],
                            'receiver_stages': snapshots,
                            'assessment': assessed})
                    for name, changes in (
                            ('suppressed-unicode', {'group': 10, 'tag_value': '12345678901234漢'}),
                            ('already-broadcast', {'group': 11, 'already_broadcast': True}),
                            ('missing-group', {'group': None})):
                        plan = compile_broadcast(request(project, **changes)).as_dict()
                        self.assertEqual(plan['commands'], [])
                        assessed = assess_broadcast(plan, {
                            'format': 'cbus-classic-dlt-broadcast-outcomes-v1',
                            'plan_sha256': plan['plan_sha256'], 'attempts': []})
                        self.assertFalse(assessed['native_accepted'])
                        self.assertEqual(assessed['original_cache_marked'], name != 'missing-group')
                        report['cases'].append({'name': name, 'commands': [], 'assessment': assessed})
                    self.assertEqual(len(simulator.labels.labels), len(cases))
                    self.assertFalse([row for row in simulator.wire_log if 'reason' in row])
                    reloaded = PCISimulator(profile='synthetic', state_path=state_path)
                    self.assertEqual(reloaded.labels.snapshot(), simulator.labels.snapshot())
                    report['synthetic_receiver_reload_equal'] = True
                    report['passed'] = True
                finally:
                    if created:
                        cleanup = (['NET CLOSE ' + network] if loaded else []) + [
                            'PROJECT CLOSE ' + project, 'PROJECT DELETE ' + project]
                        cleanup_errors = []
                        for command in cleanup:
                            try:
                                if not client.connected:
                                    client.connect()
                                client.command(command)
                            except (OSError, RuntimeError) as error:
                                cleanup_errors.append(type(error).__name__)
                        # The outer owned-service context always terminates its
                        # child and removes its isolated project directory.
                        report['project_cleanup_errors'] = cleanup_errors
                        if report['passed']:
                            self.assertEqual(cleanup_errors, [])
        if os.environ.get('CBUS_DLT_BROADCAST_REPORT'):
            Path(os.environ['CBUS_DLT_BROADCAST_REPORT']).write_text(json.dumps(report, indent=2) + '\n')
