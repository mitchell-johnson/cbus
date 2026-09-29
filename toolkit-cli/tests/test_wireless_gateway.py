import json
import os
from pathlib import Path
import unittest
from uuid import uuid4

from cbus_toolkit.unitspec import ParameterSpec, UnitSpec, UnitSpecStore
from cbus_toolkit.wireless_gateway import (
    FIELDS, LAYOUT, NO_REMOTE, OWNED, SPEC_FILENAME, WTXU_KEY_MAP, WirelessGatewayApplyError,
    WirelessGatewayEditor, WirelessGatewayError, WirelessGatewayPlan, check_profile, decode_slot,
    parse_assignment, profile_refusal, scene_count, serial_from_bytes, serial_to_bytes)
from test_macros import Session

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / 'research/fixtures/wireless-source-review.json'
RECEIPT = ROOT / 'research/fixtures/wireless-gateway-native-acceptance.json'


def fixture():
    """Synthetic spec with the admitted layout plus two unrelated parameters."""
    defaults = {'MapWirelessRemotes': '0', 'Application': '56 255', 'SceneTriggerGroup': ' '.join(['255'] * 8),
                'SceneVectorOffset': ' '.join(['255'] * 8)}
    parameters = {}
    for name, (address, size, bits, bit, skip, kind) in LAYOUT.items():
        default = defaults.get(name, ' '.join(['0' if kind == 'bit' else '255'] * size))
        fields = {'Name': name, 'Type': kind, 'Address': str(address), 'ArraySize': str(size),
                  'BitAddress': str(bit), 'ArraySkip': str(skip), 'DefaultValue': default}
        if kind == 'int':
            fields.update(BitSize=str(bits), MinValue='0', MaxValue='255')
        parameters[name] = ParameterSpec(name, kind, 'literal-wgate-fixture.xml', fields)
    for name, address, value in (('UnitAddress', 0x20, '255'), ('StatusMonitorApplication', 0x37, '56')):
        parameters[name] = ParameterSpec(name, 'int', 'literal-wgate-fixture.xml', {
            'Name': name, 'Type': 'int', 'Address': str(address), 'DefaultValue': value})
    return UnitSpec(SPEC_FILENAME, {'Type': 'WGATE5N'}, ('literal-wgate-fixture.xml',), parameters)


def session(**values):
    result = Session(fixture())
    result.unit_type, result.firmware, result.catalog_number = 'WGATE5F', '2.4.00', '5800WCGA'
    result.current.update(values)
    return result


def remote_switch(**values):
    """Remote Switch mode with two configured scenes (the second without a trigger group)."""
    return session(**{'MapWirelessRemotes': '1', 'Application': '56 202',
                      'SceneVectorOffset': '0 10 255 255 255 255 255 255',
                      'SceneTriggerGroup': '200 255 255 255 255 255 255 255', **values})


def listed(value):
    return [int(v, 0) for v in value.split()]


class SourceReviewTest(unittest.TestCase):
    def test_receipt_is_sanitized_and_pins_the_editor_rules(self):
        text = REVIEW.read_text()
        for forbidden in ('BEGIN ', 'password', '/Volumes/', 'C:\\\\Dev'):
            self.assertNotIn(forbidden, text)
        review = json.loads(text)
        gateway = review['gateway']
        self.assertEqual(gateway['key_map']['map'], list(WTXU_KEY_MAP))
        self.assertEqual((gateway['profile']['unit_type'], gateway['profile']['spec']), ('WGATE5F', SPEC_FILENAME))
        self.assertEqual(len(review['inputs']['toolkit_exe_sha256']), 64)
        self.assertIn('TFRMWIRELESSGATEWAYREMOTE', review['inputs']['form_resource_sha256'])


class ProfileTest(unittest.TestCase):
    def test_admitted_range_and_refusals(self):
        self.assertIsNone(profile_refusal('WGATE5F', '2.2.90'))
        self.assertIsNone(profile_refusal('WGATE5F', '2.4.99'))
        for unit_type, firmware, message in (('WGATE5N', '2.4.00', 'TCBusWirelessGatewayUnit'),
                                             ('WGATE5F', '2.2.89', 'firmware outside'),
                                             ('WGATE5F', '2.5.00', 'firmware outside'),
                                             ('WGATE5F', 'x', 'firmware outside'),
                                             ('WRM2D1', '2.4.00', 'Only WGATE5F')):
            with self.subTest(unit_type=unit_type, firmware=firmware):
                with self.assertRaisesRegex(WirelessGatewayError, message):
                    check_profile(unit_type, firmware)

    def test_editor_rejects_wrong_spec_or_layout(self):
        spec = fixture()
        with self.assertRaisesRegex(WirelessGatewayError, 'Use WGATE5X_2.xml'):
            WirelessGatewayEditor(UnitSpec('WGATE5X.xml', spec.metadata, spec.sources, spec.parameters))
        moved = dict(spec.parameters)
        fields = dict(moved['GroupAddress3'].fields, Address='0xD1')
        moved['GroupAddress3'] = ParameterSpec('GroupAddress3', 'int', 'literal', fields)
        with self.assertRaisesRegex(WirelessGatewayError, 'GroupAddress3'):
            WirelessGatewayEditor(UnitSpec(SPEC_FILENAME, spec.metadata, spec.sources, moved))
        missing = {k: v for k, v in spec.parameters.items() if k != 'MapWirelessRemotes'}
        with self.assertRaisesRegex(WirelessGatewayError, 'MapWirelessRemotes'):
            WirelessGatewayEditor(UnitSpec(SPEC_FILENAME, spec.metadata, spec.sources, missing))


class CodecTest(unittest.TestCase):
    def test_serial_scene_and_slot_codecs(self):
        self.assertEqual(serial_to_bytes(0x12345678), (0x78, 0x56, 0x34, 0x12))
        self.assertEqual(serial_from_bytes((0x78, 0x56, 0x34, 0x12)), 0x12345678)
        self.assertEqual(serial_from_bytes((255,) * 4), NO_REMOTE)
        self.assertEqual(scene_count((0, 0x85, 0x64, 0xE4, 255, 99, 255, 255)), 3)
        self.assertEqual(decode_slot(1, 0, 0x21)['function'], 'scene-set')
        self.assertEqual(decode_slot(1, 0, 0x26), {'function': 'scene-toggle', 'label': 'Scene Toggle', 'scene': 3,
                                                   'raw': {'mask': 1, 'secondary': 0, 'value': 0x26}})
        self.assertEqual(decode_slot(1, 0, 0x03)['function'], 'scene-toggle')
        self.assertEqual(decode_slot(0, 1, 255)['group'], None)
        self.assertEqual(decode_slot(0, 1, 7)['application'], 'secondary')
        self.assertEqual(parse_assignment('group:0x10:secondary'),
                         {'function': 'group', 'group': 16, 'application': 'secondary'})
        self.assertEqual(parse_assignment('group:none')['group'], None)
        self.assertEqual(parse_assignment('Scene-Toggle:2'), {'function': 'scene-toggle', 'scene': 2})
        for bad in ('scene:1', 'group', 'scene-set:x', 'group:1:2:3', 7):
            with self.subTest(bad=bad):
                with self.assertRaises(WirelessGatewayError):
                    parse_assignment(bad)


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.editor = WirelessGatewayEditor(fixture())

    def test_mode_switch_and_application_default_refusal(self):
        live = session()
        plan = self.editor.plan(live.values(), mode='remote-switch')
        self.assertEqual(dict(plan.changes), {'MapWirelessRemotes': (1,)})
        unassigned = session(Application='255 255')
        with self.assertRaisesRegex(WirelessGatewayError, 'Application 1 unassigned'):
            self.editor.plan(unassigned.values(), mode='remote-switch')
        back = self.editor.plan(remote_switch().values(), mode='network-gateway')
        self.assertEqual(dict(back.changes), {'MapWirelessRemotes': (0,)})
        with self.assertRaisesRegex(WirelessGatewayError, 'Remote Switch mode'):
            self.editor.plan(live.values(), remote=1, serial=5)
        with self.assertRaisesRegex(WirelessGatewayError, 'Mode must'):
            self.editor.plan(live.values(), mode='gateway')

    def test_remote_keys_use_the_wtxu_map_and_save_encoding(self):
        live = remote_switch()
        plan = self.editor.plan(live.values(), remote=3, serial=0x00A1B2C3,
                                keys={1: 'group:20', 5: 'group:21:secondary', 6: 'scene-set:1', 10: 'scene-toggle:1'})
        changes = dict(plan.changes)
        self.assertEqual(changes['RemoteIdentity3'], (0xC3, 0xB2, 0xA1, 0x00))
        groups, masks, secondary = changes['GroupAddress3'], changes['KeySceneMask3'], changes['ApplicationSeconday3']
        self.assertEqual((groups[4], masks[4], secondary[4]), (20, 0, 0))      # key 1 -> slot 5
        self.assertEqual((groups[0], masks[0], secondary[0]), (21, 0, 1))      # key 5 -> slot 1
        self.assertEqual((groups[12], masks[12]), (0x01, 1))                   # key 6 -> slot 13
        self.assertEqual((groups[8], masks[8]), (0x06, 1))                     # key 10 -> slot 9
        self.assertEqual(set(changes), {'RemoteIdentity3', 'GroupAddress3', 'KeySceneMask3', 'ApplicationSeconday3'})
        self.assertEqual(plan.raw_slot_edits, ())

    def test_key_dependencies_and_domains(self):
        live = remote_switch()
        values = live.values()
        with self.assertRaisesRegex(WirelessGatewayError, 'until a remote control is selected'):
            self.editor.plan(values, remote=1, keys={1: 'group:5'})
        with self.assertRaisesRegex(WirelessGatewayError, 'scene 2 has no trigger group'):
            self.editor.plan(values, remote=1, serial=1, keys={1: 'scene-set:2'})
        with self.assertRaisesRegex(WirelessGatewayError, 'scene 3 is not configured'):
            self.editor.plan(values, remote=1, serial=1, keys={1: 'scene-set:3'})
        no_second = remote_switch(Application='56 255')
        with self.assertRaisesRegex(WirelessGatewayError, 'application switch'):
            self.editor.plan(no_second.values(), remote=1, serial=1, keys={1: 'group:5:secondary'})
        for options, message in (({'remote': 9, 'serial': 1}, 'Remote must'),
                                 ({'remote': 1, 'serial': NO_REMOTE}, 'Remote serial'),
                                 ({'remote': 1, 'serial': 1, 'keys': {11: 'group:1'}}, 'Key must'),
                                 ({'remote': 1, 'serial': 1, 'keys': {1: 'group:256'}}, 'group must'),
                                 ({'remote': 1, 'serial': 1, 'keys': {1: 'group:1'}, 'slots': {5: 'group:2'}},
                                  'also selected'),
                                 ({'keys': {1: 'group:1'}}, 'require a remote')):
            with self.subTest(options=options):
                with self.assertRaisesRegex(WirelessGatewayError, message):
                    self.editor.plan(values, **options)

    def test_boundaries_clear_and_raw_slots(self):
        live = remote_switch(RemoteIdentity8='1 2 3 4')
        plan = self.editor.plan(live.values(), remote=8, serial=None, slots={16: 'group:none', 1: 'group:0'})
        changes = dict(plan.changes)
        self.assertEqual(changes['RemoteIdentity8'], (255,) * 4)
        self.assertEqual(changes['GroupAddress8'][0], 0)
        self.assertNotIn('KeySceneMask8', changes)   # slot 16 already 255/group, mask stays 0
        self.assertEqual(plan.raw_slot_edits, (16, 1))
        top = self.editor.plan(live.values(), remote=1, serial=NO_REMOTE - 1, keys={10: 'group:254'})
        self.assertEqual(dict(top.changes)['RemoteIdentity1'], (0xFE, 0xFF, 0xFF, 0xFF))

    def test_show_projects_toolkit_view_and_save_effects(self):
        live = remote_switch(RemoteIdentity2='0x44 0x33 0x22 0x11',
                             KeySceneMask2='1 0 0 0 1 0 0 0 0 0 0 0 0 1 0 0',
                             ApplicationSeconday2='0 0 0 0 1 0 0 0 0 0 0 0 0 0 0 0',
                             GroupAddress2='0x23 255 255 255 0x01 255 255 255 255 255 255 255 255 0x31 255 255')
        view = self.editor.show(live.values())
        self.assertEqual((view['mode'], view['applications']), ('remote-switch', {'primary': 56, 'secondary': 202}))
        self.assertEqual([s['scene'] for s in view['scenes']], [1, 2])
        remote = view['remotes'][1]
        self.assertEqual((remote['serial_hex'], remote['key_map'], len(remote['keys'])), ('11223344', 'WTXU', 10))
        self.assertEqual(remote['keys'][0], {'key': 1, 'slot': 5, 'function': 'scene-set', 'label': 'Scene Set',
                                             'scene': 1, 'raw': {'mask': 1, 'secondary': 1, 'value': 1}})
        self.assertEqual(remote['keys'][4]['slot'], 1)
        self.assertEqual([row['slot'] for row in remote['hidden_slots']], [8, 7, 6, 16, 15, 14])
        effects = ' '.join(view['toolkit_save_effects'])
        self.assertIn('slot 1 scene command 3 saves as 6', effects)
        self.assertIn('slot 5 scene key ApplicationSeconday saves as 0', effects)
        self.assertIn('slot 14 references scene 4', effects)
        self.assertEqual(view['remotes'][0]['key_map'], 'identity')
        self.assertEqual(len(view['remotes'][0]['hidden_slots']), 16)


class ApplyTest(unittest.TestCase):
    def test_apply_verifies_profile_schema_staleness_and_preserves_unrelated(self):
        editor, live = WirelessGatewayEditor(fixture()), remote_switch()
        live.current['UnitAddress'] = '12'
        plan = editor.plan(live.values(), remote=1, serial=77, keys={2: 'group:9'},
                           identity=('WGATE5F', '2.4.00', '5800WCGA'))
        result = editor.apply(live, plan)
        self.assertTrue(result['verified'])
        self.assertEqual([n for n, _ in live.calls], ['RemoteIdentity1', 'GroupAddress1'])
        self.assertEqual((live.current['UnitAddress'], live.current['StatusMonitorApplication']), ('12', '56'))
        with self.assertRaisesRegex(WirelessGatewayError, 'changed since'):
            editor.apply(live, plan)
        other = remote_switch()
        other.unit_type = 'WGATE5N'
        with self.assertRaisesRegex(WirelessGatewayError, 'Native session'):
            editor.configure(other, mode='network-gateway')
        self.assertEqual(other.calls, [])
        old = remote_switch()
        old.firmware = '2.3.00'
        with self.assertRaisesRegex(WirelessGatewayError, 'another unit type or firmware'):
            editor.apply(old, editor.plan(old.values(), mode='network-gateway',
                                          identity=('WGATE5F', '2.4.00', None)))

    def test_plan_document_roundtrip_and_partial_failure(self):
        editor, live = WirelessGatewayEditor(fixture()), remote_switch()
        plan = editor.plan(live.values(), remote=4, serial=5, slots={3: 'scene-toggle:1'},
                           identity=('WGATE5F', '2.2.90', None))
        document = json.loads(json.dumps(plan.as_dict()))
        self.assertEqual(document['format'], 'cbus-wireless-gateway-remotes-plan-v1')
        self.assertEqual(WirelessGatewayPlan.from_dict(document), plan)
        live.firmware = '2.2.90'
        live.failure = 'KeySceneMask4'
        with self.assertRaises(WirelessGatewayApplyError) as error:
            editor.apply(live, WirelessGatewayPlan.from_dict(document))
        self.assertEqual(error.exception.attempted, ('RemoteIdentity4', 'KeySceneMask4'))
        self.assertFalse(error.exception.details['saved'])
        for bad in ({'format': 'other'}, {**document, 'unit_type': 'WGATE5N'}, {**document, 'expected': 1}):
            with self.assertRaises(WirelessGatewayError):
                WirelessGatewayPlan.from_dict(bad)
        forged = WirelessGatewayPlan(plan.expected, {'Application': (1, 2)})
        with self.assertRaisesRegex(WirelessGatewayError, 'outside'):
            editor.apply(live, forged)


def native_backend():
    if os.environ.get('CBUS_NATIVE_SERVICE_BACKEND') == 'local':
        return 'local' if os.environ.get('CBUS_LOCAL_CGATE_VENDOR') and os.environ.get('CBUS_CGATE_JAVA') else None
    return 'host' if os.environ.get('CBUS_CGATE_TEST_HOST') else None


def raw_text(pp, address, count):
    """RawData hex text; C-Gate renders bytes no parameter covers as '??'."""
    return pp.get_raw_data(address, count).lines[-1].split('RawData=', 1)[1]


def raw_bytes(pp, address, count):
    return bytes.fromhex(raw_text(pp, address, count))


def start_service(cls):
    cls.service = None
    cls.host, cls.port = os.environ.get('CBUS_CGATE_TEST_HOST'), int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023'))
    if native_backend() == 'local':
        from research.local_cgate import LocalCGate
        cls.service = LocalCGate(os.environ['CBUS_LOCAL_CGATE_VENDOR'])
        cls.addClassCleanup(cls.service.close)
        (cls.service.work / 'config/access.txt').write_text('interface 127.0.0.1 Clipsal\n')
        cls.service.start()
        cls.host, cls.port = '127.0.0.1', cls.service.port
    cls.store = UnitSpecStore(os.environ['CBUS_UNITSPEC_DIR'])


class NativeProject:
    """A disposable native project with one closed database network."""
    def __init__(self, client, prefix):
        self.client, self.project = client, prefix + uuid4().hex[:6].upper()
        self.network = f'//{self.project}/254'

    def __enter__(self):
        self.client.command('PROJECT NEW ' + self.project)
        self.client.command('PROJECT USE ' + self.project)
        self.client.command('DBCREATENET 254 Wireless_Offline Cni 127.0.0.1:29999')
        self.client.command('NET LOAD DB ' + self.project)
        self.client.command('PROJECT SAVE ' + self.project)
        return self

    def __exit__(self, *exc):
        self.client.command('PROJECT CLOSE ' + self.project)
        try:
            self.client.command('PROJECT DELETE ' + self.project)
        except Exception:  # noqa: BLE001 - cleanup only; owned native C-Gate may keep the file open
            pass


# Owned database units: admitted boundaries and refused identities.
NATIVE_ADMITTED = (('2.2.90', '5800WCGA'), ('2.4.00', 'SLC5800WCGD'))
NATIVE_REFUSED = (('WGATE5N', '2.4.00', '5800WCGA'), ('WGATE5F', '2.2.89', '5800WCGA'))


@unittest.skipUnless(native_backend() and os.environ.get('CBUS_UNITSPEC_DIR'),
                     'Select native C-Gate and unit specs for wireless gateway acceptance')
class WirelessGatewayNativeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        start_service(cls)

    def check(self, pp, editor, before, case, label, expect_bytes=(), **options):
        plan = editor.plan(pp.values(), identity=(pp.unit_type, pp.firmware, pp.catalog_number), **options)
        self.assertTrue(editor.apply(pp, plan)['verified'])
        after = pp.values()
        unrelated = sorted(n for n in before if n not in OWNED)
        self.assertEqual({n: after[n] for n in unrelated}, {n: before[n] for n in unrelated})
        for address, mask, value in expect_bytes:
            self.assertEqual(raw_bytes(pp, address, 1)[0] & mask, value, (label, hex(address)))
            case['raw_byte_assertions'] += 1
        case['positive'].append(label)
        case['unrelated_parameters_preserved'] = len(unrelated)

    def refuse(self, pp, editor, case, label, pattern, **options):
        before = pp.values()
        with self.assertRaisesRegex(WirelessGatewayError, pattern):
            editor.configure(pp, **options)
        self.assertEqual(pp.values(), before)
        case['invalid'].append(label)

    def exercise(self, client, network, address, firmware, catalog, editor, report):
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer
        NativeDatabase(client).create_unit(network, address, 'Wg' + str(address), 'WGATE5F', firmware,
                                           catalog_number=catalog)
        path = f'/db{network}/p/{address}'
        case = {'unit_type': 'WGATE5F', 'firmware': firmware, 'catalog_number': catalog, 'positive': [],
                'boundary': [], 'invalid': [], 'raw_byte_assertions': 0}
        with Programmer(client).load(network, path) as pp:
            editor._verify_session(pp)
            baseline = pp.values()
            # Dependencies: two applications and two configured scenes, the
            # second without a trigger group.
            pp.set('Application', '56 202')
            pp.set('SceneVectorOffset', '0 10 255 255 255 255 255 255')
            pp.set('SceneTriggerGroup', '200 255 255 255 255 255 255 255')
            before = pp.values()
            self.refuse(pp, editor, case, 'remotes-in-gateway-mode', 'Remote Switch mode', remote=1, serial=1)
            self.check(pp, editor, before, case, 'mode-remote-switch', mode='remote-switch',
                       expect_bytes=((0x41, 0x08, 0x08),))
            self.refuse(pp, editor, case, 'keys-without-remote', 'remote control is selected',
                        remote=1, keys={1: 'group:1'})
            self.check(pp, editor, before, case, 'remote-1-serial-and-keys', remote=1, serial=0x00A1B2C3,
                       keys={1: 'group:20', 5: 'group:21:secondary', 6: 'scene-set:1', 10: 'scene-toggle:1'},
                       expect_bytes=((0x70, 255, 0xC3), (0x73, 255, 0x00), (0xB0 + 4, 255, 20),
                                     (0xB0 + 0, 255, 21), (0xA0, 0x01, 0x01), (0xB0 + 12, 255, 0x01),
                                     (0xB0 + 8, 255, 0x06), (0x91, 0x11, 0x11), (0x90, 0x01, 0x00)))
            self.check(pp, editor, before, case, 'remote-8-boundary', remote=8, serial=0xFFFFFFFE,
                       keys={10: 'group:254', 1: 'group:0'}, slots={16: 'group:none'},
                       expect_bytes=((0x8C, 255, 0xFE), (0x8F, 255, 0xFF), (0x120 + 8, 255, 254),
                                     (0x120 + 4, 255, 0), (0x120 + 15, 255, 255)))
            case['boundary'] += ['serial-FFFFFFFE', 'group-0-254-none', 'remote-8', 'slot-16', 'key-10']
            self.check(pp, editor, before, case, 'remote-8-clear', remote=8, serial=None,
                       expect_bytes=((0x8C, 255, 0xFF), (0x8D, 255, 0xFF)))
            self.refuse(pp, editor, case, 'scene-without-trigger', 'no trigger group',
                        remote=1, keys={2: 'scene-set:2'})
            self.refuse(pp, editor, case, 'scene-not-configured', 'not configured', remote=1, keys={2: 'scene-set:3'})
            self.refuse(pp, editor, case, 'serial-none-value', 'Remote serial', remote=2, serial=0xFFFFFFFF)
            pp.set('Application', '56 255')
            self.refuse(pp, editor, case, 'secondary-disabled', 'application switch',
                        remote=1, keys={3: 'group:3:secondary'})
            pp.set('Application', '56 202')
            self.check(pp, editor, before, case, 'mode-network-gateway', mode='network-gateway',
                       expect_bytes=((0x41, 0x08, 0x00),))
            after = pp.values()
            unrelated = sorted(n for n in baseline if n not in FIELDS)
            self.assertEqual({k: after[k] for k in unrelated}, {k: baseline[k] for k in unrelated})
            view = editor.show(after)
            self.assertEqual(view['remotes'][0]['keys'][5]['function'], 'scene-set')
            raw = raw_text(pp, 0x40, 0x100)
            pp.save_to_source()
        report['types'].append(case)
        report['raw_byte_assertions'] += case['raw_byte_assertions']
        report['edits'] += len(case['positive'])
        return path, after, raw

    def refuse_type(self, client, network, address, unit_type, firmware, catalog, editor, report):
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer
        NativeDatabase(client).create_unit(network, address, 'Wr' + str(address), unit_type, firmware,
                                           catalog_number=catalog)
        with Programmer(client).load(network, f'/db{network}/p/{address}') as pp:
            before = pp.values()
            with self.assertRaisesRegex(WirelessGatewayError, 'Native session'):
                editor.configure(pp, mode='remote-switch')
            self.assertEqual(pp.values(), before)
        report['refused'].append({'unit_type': unit_type, 'firmware': firmware, 'parameters': len(before),
                                  'values_unchanged': True})

    def test_remote_mapping_raw_bytes_preservation_save_reload_and_refusals(self):
        from cbus_toolkit.cgate import CGateClient
        editor = WirelessGatewayEditor(self.store.load(SPEC_FILENAME))
        report = {'format': 'cbus-wireless-gateway-acceptance-v1', 'backend': native_backend(),
                  'scope': ('Toolkit source-grounded WGATE5F Mode and Remote Control pages through native PP and '
                            'a closed database; no radio, remote pairing or physical gateway'),
                  'types': [], 'refused': [], 'edits': 0, 'raw_byte_assertions': 0, 'passed': False,
                  'physical_hardware_verified': False}
        with CGateClient(self.host, self.port, timeout=30) as client, NativeProject(client, 'WG') as project:
            report['greeting'] = client.greeting
            finals = {}
            for index, (firmware, catalog) in enumerate(NATIVE_ADMITTED):
                with self.subTest(firmware=firmware):
                    path, values, raw = self.exercise(client, project.network, 20 + index, firmware, catalog,
                                                      editor, report)
                    finals[path] = (values, raw)
            for index, (unit_type, firmware, catalog) in enumerate(NATIVE_REFUSED):
                with self.subTest(refused=unit_type, firmware=firmware):
                    self.refuse_type(client, project.network, 40 + index, unit_type, firmware, catalog,
                                     editor, report)
            client.command('PROJECT SAVE ' + project.project)
            client.command('PROJECT CLOSE ' + project.project)
            client.command('PROJECT LOAD ' + project.project)
            client.command('PROJECT USE ' + project.project)
            from cbus_toolkit.programming import Programmer
            for case, (path, (values, raw)) in zip(report['types'], finals.items()):
                with Programmer(client).load(project.network, path) as pp:
                    self.assertEqual(pp.values(), values)
                    self.assertEqual(raw_text(pp, 0x40, 0x100), raw)
                case['save_close_reload_passed'] = True
            report['passed'] = (len(report['types']) == len(NATIVE_ADMITTED)
                                and len(report['refused']) == len(NATIVE_REFUSED))
            self.assertTrue(report['passed'])
        if self.service is not None:
            report['service'] = {k: self.service.report.get(k) for k in (
                'vendor_jar_sha256', 'java_version', 'listener_ownership_verified', 'listeners')}
        if os.environ.get('CBUS_WIRELESS_REPORT'):
            Path(os.environ['CBUS_WIRELESS_REPORT']).write_text(json.dumps(report, indent=2) + '\n')


class NativeReceiptTest(unittest.TestCase):
    def test_retained_native_receipt(self):
        receipt = json.loads(RECEIPT.read_text())
        self.assertTrue(receipt['passed'])
        self.assertFalse(receipt['physical_hardware_verified'])
        self.assertEqual([t['firmware'] for t in receipt['types']], [f for f, _ in NATIVE_ADMITTED])
        self.assertEqual({(r['unit_type'], r['firmware']) for r in receipt['refused']},
                         {(t, f) for t, f, _ in NATIVE_REFUSED})
        self.assertTrue(all(t['save_close_reload_passed'] for t in receipt['types']))


if __name__ == '__main__':
    unittest.main()
