"""P5.07 focused wireless-gateway subset (issue #44).

Smallest safe native slice for WGATE5F 2.2.90..2.4.99 Mode/Remote-Switch
mapping: plan/apply/raw-byte readback/stale/preservation/save-reload plus
Advanced-workflow refusals (WGATE5N, pre-2.2.90 WGATE5F, sparse/invalid scene
offsets). Runs natively only when CBUS_CGATE_TEST_HOST and CBUS_UNITSPEC_DIR
are set; offline guard tests always run. No radio, pairing, or physical I/O.
"""
import json
import os
import unittest
from uuid import uuid4

from cbus_toolkit.wireless_gateway import (
    OWNED, SPEC_FILENAME, WirelessGatewayApplyError, WirelessGatewayEditor,
    WirelessGatewayError, validate_scene_offsets,
)
from test_macros import Session
from test_wireless_gateway import fixture, remote_switch


def native_enabled():
    return bool(os.environ.get('CBUS_CGATE_TEST_HOST') and os.environ.get('CBUS_UNITSPEC_DIR'))


class SparseOffsetGuardTest(unittest.TestCase):
    def setUp(self):
        self.editor = WirelessGatewayEditor(fixture())

    def test_validate_accepts_contiguous_and_refuses_sparse_or_invalid(self):
        validate_scene_offsets((0, 10, 255, 255, 255, 255, 255, 255))
        for bad in ((255, 0, 255, 255, 255, 255, 255, 255),   # valid after unused
                    (0, 255, 10, 255, 255, 255, 255, 255),     # gap then valid
                    (100, 255, 255, 255, 255, 255, 255, 255),  # 100 & 0x7F == 100
                    (0xE4, 255, 255, 255, 255, 255, 255, 255)):  # 228 & 0x7F == 100
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(WirelessGatewayError, 'Sparse or invalid'):
                    validate_scene_offsets(bad)

    def test_show_and_plan_refuse_sparse_without_writes(self):
        sparse = remote_switch(SceneVectorOffset='255 0 255 255 255 255 255 255')
        with self.assertRaisesRegex(WirelessGatewayError, 'Sparse or invalid'):
            self.editor.show(sparse.values())
        live = remote_switch(SceneVectorOffset='0 255 10 255 255 255 255 255')
        before, calls = live.values(), list(live.calls)
        with self.assertRaisesRegex(WirelessGatewayError, 'Sparse or invalid'):
            self.editor.plan(before, remote=1, serial=7, keys={1: 'group:5'})
        self.assertEqual(live.values(), before)
        self.assertEqual(list(live.calls), calls)


class PreservationGuardTest(unittest.TestCase):
    def test_apply_reports_preservation_and_refuses_unrelated_change(self):
        editor, live = WirelessGatewayEditor(fixture()), remote_switch()
        plan = editor.plan(live.values(), remote=1, serial=77, keys={2: 'group:9'},
                           identity=('WGATE5F', '2.4.00', '5800WCGA'))
        result = editor.apply(live, plan)
        self.assertTrue(result['verified'])
        self.assertTrue(result['unrelated_parameters_preserved'])

        class UnrelatedMutatingSession(Session):
            def set(self, name, value):
                super().set(name, value)
                self.current['UnitAddress'] = '99'

        other = UnrelatedMutatingSession(fixture())
        other.unit_type, other.firmware, other.catalog_number = 'WGATE5F', '2.4.00', '5800WCGA'
        other.current.update(remote_switch().current)
        plan = editor.plan(other.values(), remote=1, serial=78, keys={2: 'group:9'})
        with self.assertRaises(WirelessGatewayApplyError) as caught:
            editor.apply(other, plan)
        self.assertIn('Unrelated gateway parameters', str(caught.exception.cause))
        self.assertFalse(caught.exception.details['saved'])


def raw_text(pp, address, count):
    return pp.get_raw_data(address, count).lines[-1].split('RawData=', 1)[1]


def raw_bytes(pp, address, count):
    return bytes.fromhex(raw_text(pp, address, count))


@unittest.skipUnless(native_enabled(), 'Set CBUS_CGATE_TEST_HOST and CBUS_UNITSPEC_DIR for P5.07 gateway acceptance')
class WirelessGatewayP507HostTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from cbus_toolkit.unitspec import UnitSpecStore
        cls.host = os.environ['CBUS_CGATE_TEST_HOST']
        cls.port = int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023'))
        cls.store = UnitSpecStore(os.environ['CBUS_UNITSPEC_DIR'])

    def project(self, client, prefix='WG'):
        from cbus_toolkit.native import NativeDatabase
        name = prefix + uuid4().hex[:6].upper()
        network = f'//{name}/254'
        client.command('PROJECT NEW ' + name)
        try:
            client.command('PROJECT USE ' + name)
            client.command('DBCREATENET 254 Wireless_Offline Cni 127.0.0.1:29999')
            client.command('NET LOAD DB ' + name)
            client.command('PROJECT SAVE ' + name)
        except BaseException:
            try:
                client.command('PROJECT CLOSE ' + name)
            finally:
                try:
                    client.command('PROJECT DELETE ' + name)
                except Exception:  # noqa: BLE001 - cleanup only
                    pass
            raise
        return name, network

    def close_delete(self, client, name):
        try:
            client.command('PROJECT CLOSE ' + name)
        finally:
            try:
                client.command('PROJECT DELETE ' + name)
            except Exception:  # noqa: BLE001 - owned server may keep the file open
                pass

    def exercise(self, client, network, address, firmware, catalog):
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer
        NativeDatabase(client).create_unit(network, address, 'Wg%d' % address, 'WGATE5F',
                                           firmware, catalog_number=catalog)
        editor = WirelessGatewayEditor(self.store.load(SPEC_FILENAME))
        path = f'/db{network}/p/{address}'
        report = {'firmware': firmware, 'catalog_number': catalog, 'raw_byte_assertions': 0}
        with Programmer(client).load(network, path) as pp:
            editor._verify_session(pp)
            pp.set('Application', '56 202')
            pp.set('SceneVectorOffset', '0 10 255 255 255 255 255 255')
            pp.set('SceneTriggerGroup', '200 255 255 255 255 255 255 255')
            before = pp.values()
            # Sparse scene table refuses before any staging write.
            pp.set('SceneVectorOffset', '0 255 10 255 255 255 255 255')
            sparse = pp.values()
            with self.assertRaisesRegex(WirelessGatewayError, 'Sparse or invalid'):
                editor.configure(pp, remote=1, serial=9, keys={1: 'group:5'})
            self.assertEqual(pp.values(), sparse)
            pp.set('SceneVectorOffset', before['SceneVectorOffset'])
            report['sparse_scene_offsets_refused_without_write'] = True
            # Mode plan/apply with raw-byte readback.
            plan = editor.plan(pp.values(), mode='remote-switch',
                               identity=(pp.unit_type, pp.firmware, pp.catalog_number))
            result = editor.apply(pp, plan)
            self.assertTrue(result['verified'])
            self.assertTrue(result['unrelated_parameters_preserved'])
            self.assertEqual(raw_bytes(pp, 0x41, 1)[0] & 0x08, 0x08)
            report['raw_byte_assertions'] += 1
            report['mode_remote_switch_verified'] = True
            before = pp.values()
            # Remote mapping plan/apply with raw-byte readback.
            plan = editor.plan(pp.values(), remote=1, serial=0x00A1B2C3,
                               keys={1: 'group:20', 6: 'scene-set:1'},
                               identity=(pp.unit_type, pp.firmware, pp.catalog_number))
            result = editor.apply(pp, plan)
            self.assertTrue(result['verified'])
            self.assertTrue(result['unrelated_parameters_preserved'])
            self.assertEqual(raw_bytes(pp, 0x70, 4), bytes((0xC3, 0xB2, 0xA1, 0x00)))
            self.assertEqual(raw_bytes(pp, 0xB0, 16)[4], 20)
            self.assertEqual(raw_bytes(pp, 0xB0, 16)[12], 0x01)
            self.assertEqual(raw_bytes(pp, 0x90, 16)[4], 0)
            self.assertEqual(raw_bytes(pp, 0x90, 16)[12], 1)
            report['raw_byte_assertions'] += 5
            unrelated = sorted(n for n in before if n not in OWNED)
            after = pp.values()
            self.assertEqual({n: after[n] for n in unrelated}, {n: before[n] for n in unrelated})
            report['unrelated_parameters_preserved'] = len(unrelated)
            # Stale PP refuses before any staging write.
            pre_stale = pp.values()
            plan = editor.plan(pre_stale, remote=2, serial=99)
            pp.set('StatusMonitorApplication', '57')
            stale = pp.values()
            with self.assertRaisesRegex(WirelessGatewayError, 'changed since'):
                editor.apply(pp, plan)
            self.assertEqual(pp.values(), stale)
            pp.set('StatusMonitorApplication', pre_stale['StatusMonitorApplication'])
            self.assertEqual(pp.values(), pre_stale)
            report['stale_pp_refused_without_write'] = True
            # Advanced-workflow refusals leave native values unchanged.
            refusals = (
                ('remotes-with-mode-change', 'Remote Switch mode',
                 {'mode': 'network-gateway', 'remote': 1, 'serial': 1}),
                ('keys-without-remote', 'remote control is selected',
                 {'remote': 2, 'keys': {1: 'group:1'}}),
                ('scene-without-trigger', 'no trigger group',
                 {'remote': 1, 'keys': {2: 'scene-set:2'}}),
            )
            for label, pattern, options in refusals:
                with self.subTest(refusal=label):
                    snapshot = pp.values()
                    with self.assertRaisesRegex(WirelessGatewayError, pattern):
                        editor.configure(pp, **options)
                    self.assertEqual(pp.values(), snapshot)
            with self.subTest(refusal='secondary-disabled'):
                snapshot = pp.values()
                pp.set('Application', '56 255')
                try:
                    with self.assertRaisesRegex(WirelessGatewayError, 'application switch'):
                        editor.configure(pp, remote=1, keys={3: 'group:3:secondary'})
                    self.assertEqual(pp.values(), dict(snapshot, Application='56 255'))
                finally:
                    pp.set('Application', snapshot['Application'])
                self.assertEqual(pp.values(), snapshot)
            report['advanced_workflow_refusals_verified'] = True
            values, raw = pp.values(), raw_text(pp, 0x40, 0x100)
            pp.save_to_source()
        return report, path, values, raw

    def refuse_type(self, client, network, address, unit_type, firmware, catalog):
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer
        NativeDatabase(client).create_unit(network, address, 'Wr%d' % address, unit_type, firmware,
                                           catalog_number=catalog)
        editor = WirelessGatewayEditor(self.store.load(SPEC_FILENAME))
        with Programmer(client).load(network, f'/db{network}/p/{address}') as pp:
            before = pp.values()
            with self.assertRaisesRegex(WirelessGatewayError, 'Native session'):
                editor.configure(pp, mode='remote-switch')
            self.assertEqual(pp.values(), before)
        return {'unit_type': unit_type, 'firmware': firmware, 'values_unchanged': True}

    def test_p507_mode_mapping_stale_preservation_reload_and_refusals(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.programming import Programmer
        report = {'format': 'cbus-wireless-gateway-p507-acceptance-v1',
                  'scope': ('P5.07 focused WGATE5F Mode/Remote-Switch mapping through native PP '
                            'on a closed database; no radio, pairing, or physical gateway'),
                  'types': [], 'refused': [], 'passed': False, 'physical_hardware_verified': False}
        with CGateClient(self.host, self.port, timeout=30) as client:
            report['greeting'] = client.greeting
            name, network = self.project(client, 'WP')
            try:
                finals = {}
                for index, (firmware, catalog) in enumerate((('2.2.90', '5800WCGA'), ('2.4.00', 'SLC5800WCGD'))):
                    with self.subTest(firmware=firmware):
                        case, path, values, raw = self.exercise(client, network, 20 + index, firmware, catalog)
                        report['types'].append(case)
                        finals[path] = (values, raw)
                for index, (unit_type, firmware, catalog) in enumerate(
                        (('WGATE5N', '2.4.00', '5800WCGA'), ('WGATE5F', '2.2.89', '5800WCGA'))):
                    with self.subTest(refused=unit_type, firmware=firmware):
                        report['refused'].append(self.refuse_type(client, network, 40 + index, unit_type, firmware, catalog))
                client.command('PROJECT SAVE ' + name)
                client.command('PROJECT CLOSE ' + name)
                client.command('PROJECT LOAD ' + name)
                client.command('PROJECT USE ' + name)
                for path, (values, raw) in finals.items():
                    with Programmer(client).load(network, path) as pp:
                        self.assertEqual(pp.values(), values)
                        self.assertEqual(raw_text(pp, 0x40, 0x100), raw)
                report['save_close_reload_passed'] = True
                report['passed'] = len(report['types']) == 2 and len(report['refused']) == 2
                self.assertTrue(report['passed'])
            finally:
                self.close_delete(client, name)
        if os.environ.get('CBUS_WIRELESS_P507_REPORT'):
            from pathlib import Path
            Path(os.environ['CBUS_WIRELESS_P507_REPORT']).write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    unittest.main()
