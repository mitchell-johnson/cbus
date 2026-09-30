"""Classic DLT dynamic control: inverse polarity, preservation and owned C-Gate reload."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import unittest

from cbus_toolkit.dlt_controls import (ADDRESS, FLAG, MASK, ClassicDltControls, DltControlPlan)
from cbus_toolkit.dlt_labels import DltLabelError, DltLabelApplyError
from cbus_toolkit.dlt_profiles import PROFILES
from cbus_toolkit.unitspec import UnitSpecStore
from test_dlt_labels import fixture, session, NATIVE_TYPES, NEIGHBOURS
from test_macros import NATIVE, NATIVE_REASON, closed_network_project, native_endpoint


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.editor = ClassicDltControls(fixture(), 'KEYBL5')

    def test_both_polarities_with_variants_and_noop(self):
        live = session()
        self.assertFalse(self.editor.show(live.values())['block_dynamic_updates'])
        plan = self.editor.plan_controls(live.values(), block_dynamic_updates=True, variants={1: 4, 8: 2})
        self.assertEqual(plan.changes[FLAG], (0,))
        self.assertEqual(DltControlPlan.from_dict(json.loads(json.dumps(plan.as_dict()))), plan)
        result = self.editor.apply_controls(live, plan)
        self.assertTrue(result['verified'])
        self.assertFalse(result['saved'] or result['labels_transferred'])
        self.assertTrue(self.editor.show(live.values())['block_dynamic_updates'])
        self.assertEqual(dict(self.editor.plan_controls(live.values(), block_dynamic_updates=True).changes), {})
        result = self.editor.configure_controls(live, block_dynamic_updates=False)
        self.assertEqual(result['changes'], {FLAG: [1]})
        self.assertEqual(live.current['LabelFlavourLSB'], '1 0 0 0 0 0 0 1')

    def test_bad_input_and_forged_plan_refused_before_writes(self):
        live = session()
        for value in (0, 1, None, 'yes'):
            with self.subTest(value=value), self.assertRaises(DltLabelError):
                self.editor.plan_controls(live.values(), block_dynamic_updates=value)
        for value in ('', '2', '0 1', True, [False]):
            with self.subTest(raw=value), self.assertRaises(DltLabelError):
                self.editor.plan_controls({**live.values(), FLAG: value}, block_dynamic_updates=True)
        plan = self.editor.plan_controls(live.values(), block_dynamic_updates=True)
        for forged in (replace(plan, changes={FLAG: (1,)}),
                       replace(plan, changes={FLAG: (False,)}),
                       replace(plan, changes={FLAG: (0.0,)}),
                       replace(plan, changes={**plan.changes, 'EnableSceneToggle': (1,)}),
                       replace(plan, variants=((1, 4), (1, 2))),
                       replace(plan, expected={**plan.expected, FLAG: (2,)}),
                       replace(plan, block_dynamic_updates=False),
                       replace(plan, identity=('KEYBL5', '2.1.00', '5055DL'))):
            with self.subTest(plan=forged), self.assertRaises(DltLabelError):
                self.editor.apply_controls(live, forged)
            self.assertEqual(live.calls, [])
        combined = self.editor.plan_controls(live.values(), block_dynamic_updates=True, variants={1: 4})
        for value in (False, 0.0):
            serialized = combined.as_dict()
            serialized['changes'][FLAG] = [value]
            with self.assertRaisesRegex(DltLabelError, 'exact integers'):
                self.editor.apply_controls(live, DltControlPlan.from_dict(serialized))
            self.assertEqual(live.calls, [])
        for selections in ([[1, 4], ['2', 2]], [[True, 4]], [[1.0, 4]], [[1, '4']]):
            serialized = combined.as_dict()
            serialized['requested']['variants'] = selections
            with self.assertRaises(DltLabelError):
                self.editor.apply_controls(live, DltControlPlan.from_dict(serialized))
            self.assertEqual(live.calls, [])

    def test_stale_control_and_native_schema_fail_closed(self):
        live = session()
        plan = self.editor.plan_controls(live.values(), block_dynamic_updates=True)
        live.current[FLAG] = '0'
        with self.assertRaisesRegex(DltLabelError, 'changed since'):
            self.editor.apply_controls(live, plan)
        live.current[FLAG] = '1'
        live.spec.parameters[FLAG] = replace(live.spec.parameters[FLAG], fields={
            **live.spec.parameters[FLAG].fields, 'BitAddress': '5'})
        with self.assertRaisesRegex(DltLabelError, 'layout mismatch'):
            self.editor.apply_controls(live, plan)
        self.assertEqual(live.calls, [])

    def test_partial_failure_does_not_retry_or_save(self):
        live = session()
        live.failure = FLAG
        with self.assertRaises(DltLabelApplyError) as caught:
            self.editor.configure_controls(live, block_dynamic_updates=True, variants={1: 4})
        self.assertEqual(caught.exception.attempted, ('LabelFlavourLSB', 'LabelFlavourMSB', FLAG))
        self.assertEqual(len(live.calls), 3)
        self.assertFalse(caught.exception.details['saved'])

    def test_raw_bit_mismatch_before_write_and_unowned_bit_drift_after(self):
        live = session()
        class Reply:
            def __init__(self, byte):
                self.lines = ('347 RawData=' + bytes([byte]).hex(),)
        live.get_raw_data = lambda start, count: Reply(0)
        with self.assertRaisesRegex(DltLabelError, 'raw bit disagrees'):
            self.editor.configure_controls(live, block_dynamic_updates=True)
        self.assertEqual(live.calls, [])
        raw = iter((0xFF, 0x9F))  # bit5 changed as well as the owned bit6.
        live.get_raw_data = lambda start, count: Reply(next(raw))
        with self.assertRaisesRegex(DltLabelApplyError, 'unrelated bits'):
            self.editor.configure_controls(live, block_dynamic_updates=True)
        self.assertEqual(live.calls, [(FLAG, '0')])


@unittest.skipUnless(NATIVE, NATIVE_REASON)
class NativeControlTests(unittest.TestCase):
    def test_original_cgate_database_preservation_and_save_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer
        store = UnitSpecStore(os.environ['CBUS_UNITSPEC_DIR'])
        report = {'format': 'cbus-classic-dlt-controls-native-v1', 'passed': False,
                  'scope': 'Owned original C-Gate synthetic database units only',
                  'physical_hardware_verified': False, 'original_full_form_save_executed': False,
                  'specs': {name: hashlib.sha256((store.directory / name).read_bytes()).hexdigest()
                            for name in ('KEYL4.xml', 'KEYL5.xml', 'I_DLT.xml', 'I_NEOCORE.xml')}, 'cases': []}
        with native_endpoint() as (host, port), CGateClient(host, port=port, timeout=30) as client, \
                closed_network_project(client, 'DU') as project:
            database, programmer = NativeDatabase(client), Programmer(client)
            report['greeting'] = client.greeting
            network = f'//{project}/254'
            finals = {}
            for index, identity in enumerate(NATIVE_TYPES):
                kind, firmware, catalog = identity
                path = f'{network}/p/{20 + index}'
                database.create_unit(network, 20 + index, f'DltControl{index}', kind, firmware, catalog_number=catalog)
                editor = ClassicDltControls(store.load(PROFILES[kind].spec_filename), kind)
                case = {'unit_type': kind, 'firmware': firmware, 'catalog_number': catalog, 'steps': []}
                with programmer.load(network, '/db' + path) as pp:
                    # Give every unowned bit a sentinel, including the bits
                    # that have no named PP field in the unit specification.
                    pp.set_raw_data(ADDRESS, b'\xff')
                    for name, values in NEIGHBOURS.items():
                        pp.set(name, ' '.join(map(str, values)))
                    baseline = pp.values()
                    for blocked in (True, False, True):
                        result = editor.configure_controls(pp, block_dynamic_updates=blocked,
                                                           variants={1: 4, 8: 3})
                        self.assertTrue(result['raw_bytes_verified'])
                        self.assertEqual(result['dynamic_control_raw_after'], 0xBF if blocked else 0xFF)
                        self.assertEqual({k: v for k, v in pp.values().items()
                                          if k not in (FLAG, 'LabelFlavourLSB', 'LabelFlavourMSB')},
                                         {k: v for k, v in baseline.items()
                                          if k not in (FLAG, 'LabelFlavourLSB', 'LabelFlavourMSB')})
                        case['steps'].append({'block_dynamic_updates': blocked,
                                              'raw_before': result['dynamic_control_raw_before'],
                                              'raw_after': result['dynamic_control_raw_after'],
                                              'all_other_pp_preserved': True})
                    pp.save_to_source()
                    finals[path] = pp.values()
                report['cases'].append(case)
            client.command('PROJECT SAVE ' + project)
            client.command('PROJECT CLOSE ' + project)
            client.command('PROJECT LOAD ' + project)
            client.command('PROJECT USE ' + project)
            for path, expected in finals.items():
                with programmer.load(network, '/db' + path) as pp:
                    self.assertEqual(pp.values(), expected)
                    self.assertEqual(ClassicDltControls._raw_flag(pp), 0xBF)
            report['project_save_close_reload_passed'] = True
            report['passed'] = True
        if os.environ.get('CBUS_DLT_CONTROL_REPORT'):
            Path(os.environ['CBUS_DLT_CONTROL_REPORT']).write_text(json.dumps(report, indent=2) + '\n')
