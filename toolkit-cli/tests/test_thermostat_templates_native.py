"""Original thermostat Load Template overlays against an owned isolated C-Gate.

Expected values are computed here from the raw decoded template XML, not from
``cbus_toolkit.thermostat_templates``.  Requires CBUS_CGATE_JAVA,
CBUS_LOCAL_CGATE_VENDOR and CBUS_UNITSPEC_DIR.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import unittest
from uuid import uuid4
import xml.etree.ElementTree as ET

import cbus_toolkit
from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.native import NativeDatabase, NativeProjects
from cbus_toolkit.programming import Programmer, xml_text
from cbus_toolkit.thermostat_templates import (NativeThermostatTemplates, ThermostatTemplateCatalog,
                                               ThermostatTemplateError)

SPEC_DIR = os.environ.get('CBUS_UNITSPEC_DIR')
# (unit type, catalogue number, template prefix, installation numbers)
CASES = (
    ('PC_TSA', '5070THP,BK', 'THERMOSTATA_TEMPLATE', (1, 2, 3, 4, 5)),
    ('PC_TSA5', '5070THPR,BK', 'THERMOSTATA_TEMPLATE', (6, 7, 8, 9)),
    ('PC_TSB', '5070THB,BK', 'THERMOSTAT_TEMPLATE', (1, 4, 5)),
    ('PC_TSB5', '5070THBR,BK', 'THERMOSTAT_TEMPLATE', (6, 8, 9)),
)
# Non-template parameters given non-default values before each template load.
UNRELATED = {'BacklightActiveTime': '7', 'SetbackLevel': '3', 'TemperatureOffset': '2'}


def _root(name):
    data = (Path(SPEC_DIR) / name).read_bytes()
    return ET.fromstring(data.split(b'\n', 1)[1] if data.startswith(b'(C)') else data)


def expected_template(name):
    """Independent overlay: included template first, then this file's params."""
    root = _root(name)
    result = {}
    for include in root.iter('Include'):
        result.update(expected_template(include.text.strip()))
    for param in root.find('Parameters').findall('Param'):
        text = param.findtext('DefaultValue').strip()
        result[param.findtext('Name').strip()] = int(text[1:], 16) if text.startswith('$') else int(text)
    return result


def ranges(unit_spec):
    result = {}
    for name in ('THERMOSTAT.xml', unit_spec):
        for param in _root(name).find('Parameters').findall('Param'):
            low, high = param.findtext('MinValue'), param.findtext('MaxValue')
            if low and high:
                result[param.findtext('Name').strip()] = tuple(
                    int(v.strip()[1:], 16) if v.strip().startswith('$') else int(v) for v in (low, high))
    return result


def unit_node(database, path):
    return ET.fromstring(xml_text(database.get(path, xml=True)))


@unittest.skipUnless(os.environ.get('CBUS_CGATE_JAVA') and os.environ.get('CBUS_LOCAL_CGATE_VENDOR')
                     and SPEC_DIR, 'Select Java11/vendor/unit specifications for native thermostat templates')
class NativeThermostatTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from research.local_cgate import LocalCGate
        cls.service = LocalCGate(os.environ['CBUS_LOCAL_CGATE_VENDOR'])
        cls.sentinel = socket.socket()
        # Cleanups run in reverse: close the service, record, then the sentinel.
        cls.addClassCleanup(cls.sentinel.close)
        cls.addClassCleanup(cls.finish)
        cls.addClassCleanup(cls.service.close)
        cls.sentinel.bind(('127.0.0.1', 0))
        cls.sentinel.listen(1)
        cls.sentinel.settimeout(0.05)
        (cls.service.work / 'config/access.txt').write_text('interface 127.0.0.1 Clipsal\n')
        cls.evidence = {}
        cls.service.start()
        cls.evidence = {'format': 'native-thermostat-template-integration-v1',
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
        destination = os.environ.get('CBUS_THERMOSTAT_TEMPLATE_EVIDENCE')
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

    def prepare(self, address, unit_type, catalog, expected, bounds):
        path = self.network + '/p/' + str(address)
        self.database.create_unit(self.network, address, 'Tstat' + str(address), unit_type, '5.4.01',
                                  catalog_number=catalog)
        # Every template parameter starts one step away from the template
        # value so each one must be rewritten by the overlay.
        with self.session(path) as session:
            for name, value in expected.items():
                low, high = bounds[name]
                session.set(name, str(value - 1 if value > low else value + 1 if value < high else value))
            for name, value in UNRELATED.items():
                session.set(name, value)
            session.save_to_source()
        return path

    def test_every_offered_template_overlays_and_persists(self):
        address = 10
        paths = []
        for unit_type, catalog, prefix, numbers in CASES:
            unit_spec = 'THERMOSTATA.xml' if prefix.startswith('THERMOSTATA') else 'THERMOSTATB.xml'
            bounds = ranges(unit_spec)
            for number in numbers:
                expected = expected_template(prefix + format(number, '02d') + '.xml')
                paths.append((self.prepare(address, unit_type, catalog, expected, bounds),
                              unit_type, number, expected))
                address += 1
        self.reload()
        self.assertEqual(len(paths), 15)
        for path, unit_type, number, expected in paths:
            with self.session(path) as session:
                before = session.values()
            before_node = unit_node(self.database, path)
            manager = NativeThermostatTemplates(self.client, self.catalog)
            plan = manager.plan(path, number, exclusive_project=True)
            self.assertEqual(len(plan.overlay.changes), len(expected))
            backup = 'B' + uuid4().hex[:7].upper()
            result = manager.apply(plan, backup_project=backup)
            self.assertTrue(result['complete'] and result['persistence_verified'], result)
            self.assertTrue(result['unit_record_preserved'] and result['unrelated_parameters_preserved'])
            self.projects.operation('use', self.project)
            with self.session(path) as session:
                after = session.values()
            self.assertEqual({n: int(after[n], 0) for n in expected}, expected)
            self.assertEqual({n: v for n, v in after.items() if n not in expected},
                             {n: v for n, v in before.items() if n not in expected})
            self.assertEqual({n: int(after[n], 0) for n in UNRELATED},
                             {n: int(v) for n, v in UNRELATED.items()})
            after_node = unit_node(self.database, path)
            for field in ('OID', 'UnitType', 'FirmwareVersion', 'CatalogNumber'):
                self.assertEqual(after_node.findtext(field), before_node.findtext(field))
            self.evidence['cases'].append({'path': path, 'unit_type': unit_type, 'template': number,
                                           'template_parameters': len(expected),
                                           'changed': len(plan.overlay.changes),
                                           'preserved_parameters': len(after) - len(expected),
                                           'backup': backup, 'result_state': result['state']})
        # A second plan for the last unit is a read-only no-op.
        manager = NativeThermostatTemplates(self.client, self.catalog)
        plan = manager.plan(paths[-1][0], paths[-1][2], exclusive_project=True)
        self.assertEqual(manager.apply(plan)['state'], 'already_applied')

    def test_refuses_unoffered_and_non_thermostat_pairs_without_writes(self):
        basic = self.network + '/p/30'
        self.database.create_unit(self.network, 30, 'Basic', 'PC_TSB', '5.4.01', catalog_number='5070THB,BK')
        self.database.create_unit(self.network, 31, 'Key', 'KEY4', '1.2.67', catalog_number='5034N')
        self.reload()
        before = xml_text(self.database.get('//' + self.project, xml=True))
        refusals = []
        for path, number in ((basic, 2), (basic, 3), (basic, 7), (self.network + '/p/31', 1)):
            manager = NativeThermostatTemplates(self.client, self.catalog)
            with self.assertRaises(Exception) as caught:
                manager.plan(path, number, exclusive_project=True)
            self.assertIsInstance(caught.exception.cause, ThermostatTemplateError)
            refusals.append({'path': path, 'template': number, 'error': str(caught.exception.cause)})
        self.assertEqual(xml_text(self.database.get('//' + self.project, xml=True)), before)
        self.evidence['refusals'] = refusals

    def test_public_cli_preview_and_apply(self):
        path = self.prepare(40, 'PC_TSA', '5070THP,BK', expected_template('THERMOSTATA_TEMPLATE02.xml'),
                            ranges('THERMOSTATA.xml'))
        self.reload()
        environment = dict(os.environ)
        environment['PYTHONPATH'] = str(Path(cbus_toolkit.__file__).resolve().parent.parent)
        base = [sys.executable, '-m', 'cbus_toolkit', '--compact', 'thermostat', 'template']

        def invoke(action, *extra, code=0):
            process = subprocess.run(base + [action, path, '--template', '2', '--host', '127.0.0.1',
                                             '--port', str(self.service.port), *extra],
                                     capture_output=True, text=True, timeout=120, env=environment,
                                     stdin=subprocess.DEVNULL)
            self.assertEqual(process.returncode, code, process.stderr)
            return json.loads(process.stdout if code == 0 else process.stderr)

        refused = invoke('preview', code=1)
        self.assertIn('--exclusive-project', refused['error'])
        before = xml_text(self.database.get('//' + self.project, xml=True))
        preview = invoke('preview', '--exclusive-project')
        self.assertTrue(preview['apply_would_mutate'])
        self.assertEqual(xml_text(self.database.get('//' + self.project, xml=True)), before)
        result = invoke('apply', '--exclusive-project')
        self.assertEqual(result['state'], 'verified_saved')
        self.assertTrue(result['persistence_verified'])
        self.evidence['cli'] = {'preview_changed': len(preview['changed_parameters']),
                                'apply_state': result['state']}


if __name__ == '__main__':
    unittest.main()
