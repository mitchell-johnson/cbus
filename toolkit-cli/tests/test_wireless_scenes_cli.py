"""Scenes command boundaries with literal fixtures and no socket or radio I/O."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from cbus_toolkit.cli import build_parser, main
from cbus_toolkit.wireless_cli import preflight
from cbus_toolkit.wireless_gateway import WirelessGatewayEditor
from cbus_toolkit.wireless_scenes import FrozenSceneProject, WirelessScenesEditor
from test_wireless_connection_cli import ClosedClient, MockProgrammer, response, write_spec
from test_wireless_scenes import SceneSession, fixture, project_xml, scene, two_scenes


SCENE_FIELDS = ('SceneTriggerGroup', 'SceneTriggerLevel', 'SceneTriggerRate',
                'SceneVectorOffset', 'SceneVector')
EXPECTED = {
    'SceneTriggerGroup': [10, 11, 255, 255, 255, 255, 255, 255],
    'SceneTriggerLevel': [20, 21, 255, 255, 255, 255, 255, 255],
    'SceneTriggerRate': [5, 15, 0, 0, 0, 0, 0, 0],
    'SceneVectorOffset': [0, 133, 255, 255, 255, 255, 255, 255],
    'SceneVector': [7, 0, 9, 255, 255, 3, 128, 255, *range(8, 100)],
}


class SceneCliSession(SceneSession):
    def __init__(self):
        super().__init__(RemoteIdentity1='12 34 56 78',
                         GroupAddress1='9 8 7 6 5 4 3 2 1 0 11 12 13 14 15 16',
                         ApplicationSeconday1='0 1 0 1 0 1 0 1 0 1 0 1 0 1 0 1')
        self.saves = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def save_to_source(self):
        self.saves.append(self.source)
        return response('200 Saved')


class SceneClient(ClosedClient):
    def __init__(self):
        super().__init__()
        self.document = project_xml()
        self.session = SceneCliSession()


class WirelessScenesCliTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.spec = fixture()
        write_spec(self.folder, self.spec)
        self.current = SceneCliSession().current
        self.snapshot = self.folder / 'snapshot.json'
        self.snapshot.write_text(json.dumps({
            'format': 'cbus-cli-parameters-v1', 'unit_type': 'WGATE5F', 'firmware': '2.4.00',
            'catalog_number': None, 'parameters': self.current,
        }))
        self.project = self.folder / 'project.xml'
        self.project.write_bytes(project_xml())
        self.scene_file = self.folder / 'scenes.json'
        self.scene_file.write_text(json.dumps(two_scenes()))
        self.editor = WirelessScenesEditor(self.spec)
        self.plan = self.editor.plan(self.current, project=FrozenSceneProject.from_xml(project_xml()),
                                     source_network=254, unit_address=200, scenes=two_scenes(),
                                     identity=('WGATE5F', '2.4.00', None))
        self.plan_file = self.folder / 'plan.json'
        self.plan_file.write_text(json.dumps(self.plan.as_dict()))

    def offline(self, action, *options):
        return ['wireless', '--spec-dir', str(self.folder), 'scenes', action, str(self.snapshot),
                '--project-xml', str(self.project), '--source-network', '254', '--gateway-address', '200',
                *(['--scenes', str(self.scene_file)] if action == 'plan' else []), *map(str, options)]

    def native(self, *options, unit_options=(), exclusive=True):
        return ['cgate', '--host', '127.0.0.1', '--port', '1', 'unit', '--lock-address', '//P/254',
                '--source', '/db//P/254/p/200', *map(str, unit_options), 'wireless-gateway',
                '--spec-dir', str(self.folder), '--plan', str(self.plan_file),
                *(['--exclusive-project'] if exclusive else []), *map(str, options)]

    def invoke(self, argv, expected=0):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            status = main(argv)
        self.assertEqual(status, expected, output.getvalue() + errors.getvalue())
        return json.loads(output.getvalue() or errors.getvalue())

    def mocked_native(self, client, argv=None, expected=0):
        with patch('cbus_toolkit.cgate.CGateClient', return_value=client), \
                patch('cbus_toolkit.programming.Programmer', MockProgrammer):
            return self.invoke(self.native() if argv is None else argv, expected)

    def test_offline_show_and_full_replacement_plan_have_literal_bytes_without_connection(self):
        with patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('No socket allowed')) as connect:
            view = self.invoke(self.offline('show'))
            plan = self.invoke(self.offline('plan'))
        connect.assert_not_called()
        self.assertEqual(view['format'], 'cbus-wireless-scenes-v1')
        self.assertEqual(view['scenes'], [])
        self.assertTrue(view['scene_controls_visible'])
        self.assertEqual(plan['format'], 'cbus-wireless-scenes-plan-v1')
        self.assertEqual(plan['scenes'], two_scenes())
        self.assertEqual(plan['changes'], EXPECTED)
        for flag in ('saved', 'metadata_created', 'original_toolkit_executed',
                     'whole_dialog_save_executed', 'device_verified'):
            self.assertFalse(plan[flag])
        self.assertTrue(plan['remote_mappings_preserved'])

    def test_offline_requires_selection_and_explicit_full_scene_document(self):
        for option in ('--project-xml', '--source-network', '--gateway-address', '--scenes'):
            arguments = self.offline('plan')
            index = arguments.index(option)
            del arguments[index:index + 2]
            with self.subTest(option=option), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(arguments)
            self.assertEqual(error.exception.code, 2)

    def test_offline_malformed_scene_documents_refuse_without_connection(self):
        for contents in ('null', '{}', '{bad', '[{"application":"primary"}]',
                         '[{"rate":5,"rate":6}]', '[NaN]'):
            self.scene_file.write_text(contents)
            with self.subTest(contents=contents), \
                    patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('No socket allowed')) as connect:
                result = self.invoke(self.offline('plan'), 1)
            self.assertTrue(result['error'])
            connect.assert_not_called()

    def test_offline_empty_list_is_explicit_clear_and_preserves_vector(self):
        self.scene_file.write_text('[]')
        result = self.invoke(self.offline('plan'))
        self.assertEqual(result['scenes'], [])
        self.assertEqual(result['changes'], {'SceneTriggerRate': [0] * 8})
        self.assertEqual(result['expected']['SceneVector'], list(range(100)))

    def test_valid_scene_plan_target_and_mixed_edit_refusals_precede_client_construction(self):
        temporary = self.native(unit_options=('--firmware', '2.4.00'))
        index = temporary.index('--source')
        temporary[index:index + 2] = ['--unit-type', 'WGATE5F']
        cases = {
            'physical source': self.native(unit_options=('--source', '//P/254/p/200')),
            'physical with DB destination': self.native(unit_options=(
                '--source', '//P/254/p/200', '--destination', '/db//P/254/p/200')),
            'destination even same source': self.native(unit_options=('--destination', '/db//P/254/p/200')),
            'different project': self.native(unit_options=('--source', '/db//OTHER/254/p/200')),
            'different unit': self.native(unit_options=('--source', '/db//P/254/p/199')),
            'different source network': self.native(unit_options=('--source', '/db//P/200/p/200')),
            'different lock': self.native(unit_options=('--lock-address', '//P/200')),
            'new unit': temporary,
            'no exclusive ownership': self.native(exclusive=False),
            'show': self.native('--show'),
            'mode': self.native('--mode', 'remote-switch'),
            'remote': self.native('--remote', 1),
            'serial': self.native('--serial', 'none'),
            'key': self.native('--remote-key', '1=group:7'),
            'slot': self.native('--remote-slot', '1=group:7'),
        }
        for label, argv in cases.items():
            with self.subTest(case=label), \
                    patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('No socket allowed')) as connect:
                result = self.invoke(argv, 1)
            self.assertTrue(result['error'])
            connect.assert_not_called()

    def test_malformed_forged_or_unsupported_saved_plans_refuse_before_client(self):
        valid = self.plan.as_dict()
        cases = {}
        for label, mutate in (
            ('changed prefix', lambda d: d['changes']['SceneVector'].__setitem__(0, 8)),
            ('changed preserved tail', lambda d: d['changes']['SceneVector'].__setitem__(99, 98)),
            ('omitted write', lambda d: d['changes'].pop('SceneTriggerGroup')),
            ('unowned write', lambda d: d['changes'].__setitem__('MapWirelessRemotes', [0])),
            ('missing stale dependency', lambda d: d['expected'].pop('RemoteIdentity8')),
            ('metadata digest', lambda d: d['project'].__setitem__('facts_sha256', '0' * 64)),
            ('unsupported unit', lambda d: d.__setitem__('unit_type', 'WGATE5N')),
            ('unsupported firmware', lambda d: d.__setitem__('firmware', '2.5.00')),
            ('different scene definition', lambda d: d['scenes'][0].__setitem__('rate', 2)),
        ):
            document = deepcopy(valid)
            mutate(document)
            cases[label] = json.dumps(document)
        cases.update({'missing': None, 'invalid JSON': '{bad', 'null': 'null', 'array': '[]',
                      'empty object': '{}', 'unknown format': '{"format":"unknown"}',
                      'duplicate JSON keys': '{"format":"one","format":"two"}'})
        for label, contents in cases.items():
            if contents is None:
                self.plan_file.unlink(missing_ok=True)
            else:
                self.plan_file.write_text(contents)
            with self.subTest(case=label), \
                    patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('No socket allowed')) as connect, \
                    redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(self.native())
            self.assertEqual(error.exception.code, 2)
            connect.assert_not_called()

    def test_preflight_checks_spec_layout_before_connecting_or_loading_pp(self):
        path = self.folder / self.spec.filename
        document = ET.parse(path)
        for node in document.findall('./Parameters/Param'):
            if node.findtext('Name') == 'SceneVector':
                node.find('ArraySize').text = '99'
        document.write(path)
        with patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('No socket allowed')) as connect, \
                patch('cbus_toolkit.programming.Programmer') as programmer:
            result = self.invoke(self.native(), 1)
        self.assertIn('SceneVector', result['error'])
        connect.assert_not_called()
        programmer.assert_not_called()

    def test_native_apply_refreshes_closed_metadata_sets_only_five_arrays_and_saves_once(self):
        client = SceneClient()
        before = dict(client.session.current)
        result = self.mocked_native(client)
        self.assertTrue(result['verified'])
        self.assertTrue(result['saved'])
        self.assertEqual(result['destination'], '/db//P/254/p/200')
        self.assertEqual(result['changes'], EXPECTED)
        self.assertEqual(client.commands, ['DBGETXML //P', 'GET //P/254 *'])
        self.assertEqual(client.loads, [('//P/254', '/db//P/254/p/200')])
        self.assertEqual(client.session.saves, ['/db//P/254/p/200'])
        self.assertEqual(client.session.calls, [(name, ' '.join(map(str, EXPECTED[name]))) for name in SCENE_FIELDS])
        self.assertEqual({name: value for name, value in client.session.current.items() if name not in SCENE_FIELDS},
                         {name: value for name, value in before.items() if name not in SCENE_FIELDS})
        self.assertFalse(result['device_verified'])
        self.assertFalse(result['whole_dialog_save_executed'])

    def test_native_dry_run_stages_and_verifies_but_never_saves(self):
        client = SceneClient()
        result = self.mocked_native(client, self.native(unit_options=('--dry-run',)))
        self.assertTrue(result['verified'])
        self.assertFalse(result['saved'])
        self.assertIsNone(result['destination'])
        self.assertEqual(len(client.session.calls), 5)
        self.assertEqual(client.session.saves, [])

    def test_stale_project_open_network_and_stale_remote_dependency_prevent_set_or_save(self):
        clients = [('metadata', SceneClient()), ('open', SceneClient()), ('PP remote', SceneClient())]
        clients[0][1].document = project_xml().replace(b'Group 7', b'Renamed group 7')
        clients[1][1].open_network = '//P/254'
        clients[2][1].session.current['RemoteIdentity1'] = '99 34 56 78'
        for label, client in clients:
            with self.subTest(case=label):
                result = self.mocked_native(client, expected=1)
            self.assertTrue(result['error'])
            self.assertEqual(client.session.calls, [])
            self.assertEqual(client.session.saves, [])

    def test_cached_scene_plan_cannot_be_switched_after_client_construction(self):
        alternate = self.editor.plan(self.current, project=self.plan.project, source_network=254,
                                     unit_address=200, scenes=[scene(((7, 77),))], identity=self.plan.identity)
        remote = WirelessGatewayEditor(self.spec).plan(
            self.current, mode='network-gateway', identity=self.plan.identity)
        for replacement in ('{invalid replacement', json.dumps(alternate.as_dict()), json.dumps(remote.as_dict())):
            self.plan_file.write_text(json.dumps(self.plan.as_dict()))
            client = SceneClient()

            def connect_after_preflight(*args, **kwargs):
                self.plan_file.write_text(replacement)
                return client

            with self.subTest(replacement=replacement[:80]), \
                    patch('cbus_toolkit.cgate.CGateClient', side_effect=connect_after_preflight), \
                    patch('cbus_toolkit.programming.Programmer', MockProgrammer):
                result = self.invoke(self.native())
            self.assertEqual(result['changes'], EXPECTED)
            self.assertEqual(client.session.saves, ['/db//P/254/p/200'])

    def test_cached_legacy_remote_plan_cannot_switch_to_scenes_after_connect(self):
        remote = WirelessGatewayEditor(self.spec).plan(
            self.current, mode='network-gateway', identity=self.plan.identity)
        self.plan_file.write_text(json.dumps(remote.as_dict()))
        client = SceneClient()

        def connect_after_preflight(*args, **kwargs):
            self.plan_file.write_text(json.dumps(self.plan.as_dict()))
            return client

        with patch('cbus_toolkit.cgate.CGateClient', side_effect=connect_after_preflight) as connect, \
                patch('cbus_toolkit.programming.Programmer', MockProgrammer):
            result = self.invoke(self.native())
        self.assertEqual(result['format'], 'cbus-wireless-gateway-remotes-plan-v1')
        self.assertEqual(client.session.calls, [('MapWirelessRemotes', '0')])
        self.assertEqual(client.commands, [])
        self.assertNotIn('max_line_bytes', connect.call_args.kwargs)

    def test_saved_plan_size_limit_is_32_mib_and_checks_before_connection(self):
        # Sparse files exercise the real bounded reader without consuming disk.
        original = self.plan_file.read_bytes()
        for size, accepted in ((1024 * 1024 + 1, True), (32 * 1024 * 1024 + 1, False)):
            with self.plan_file.open('wb') as stream:
                stream.write(original)
                if accepted:
                    stream.write(b' ' * (size - len(original)))
                else:
                    stream.truncate(size)
            with self.subTest(size=size), \
                    patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('No socket allowed')) as connect:
                if accepted:
                    parsed = build_parser().parse_args(self.native())
                    limits = preflight(parsed)
                    self.assertEqual(limits, {'max_line_bytes': 16 * 1024 * 1024 + 4096,
                                              'max_response_bytes': 16 * 1024 * 1024 + 65536})
                else:
                    with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                        main(self.native())
                    self.assertEqual(error.exception.code, 2)
            connect.assert_not_called()

    def test_project_payload_limit_remains_16_mib_before_set_or_save(self):
        client = SceneClient()
        base = project_xml()
        padding = b'x' * (16 * 1024 * 1024 + 1 - len(base) - len(b'<!---->'))
        client.document = base.replace(b'<Installation>', b'<Installation><!--' + padding + b'-->')
        self.assertEqual(len(client.document), 16 * 1024 * 1024 + 1)
        result = self.mocked_native(client, expected=1)
        self.assertIn('16 MiB', result['error'])
        self.assertEqual(client.session.calls, [])
        self.assertEqual(client.session.saves, [])


if __name__ == '__main__':
    unittest.main()
