"""Scene live CLI request selection, capture persistence and failure evidence."""
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import io, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from cbus_toolkit import cli
from cbus_toolkit.edlt_scene_live_cli import SceneCaptureCLIEditor
from tests.test_edlt_scene_live import Client, get, reply, vectors
from tests.test_edlt_scene_manager import cache, fixture, Session


class ConnectedClient(Client):
    connected = False
    def __enter__(self): self.connected = True; return self
    def __exit__(self, *args): self.connected = False


class SceneLiveCLITests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture(); self.session = Session(self.spec)
        self.session.current.update({k: v for k, v in vectors()['input'].items() if k in self.spec.parameters})
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name); self.source, self.cache = self.folder/'source.json', self.folder/'cache.json'
        self.source.write_text(json.dumps(self.session.values())); self.cache.write_text(json.dumps(cache()))

    def flags(self, network='//OWNED/254'):
        return ('--metadata', self.cache, '--network', network, '--scene', 1)

    def broadcast(self, *extra):
        return ('cgate', 'edlt-scene-broadcast', self.source, *self.flags(), *extra)

    def capture(self, *extra):
        return ('cgate', 'unit', '--lock-address', '//EDLTTEST/254', '--source', self.session.source,
                *extra, 'edlt-scene-capture', *self.flags())

    def invoke(self, args, status=0):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err): actual = cli.main(list(map(str, args)))
        self.assertEqual(actual, status, out.getvalue()+err.getvalue())
        return json.loads(out.getvalue() or err.getvalue())

    def test_broadcast_preflight_selection_and_definite_rejection_exit_status(self):
        with patch('cbus_toolkit.edlt_global_cli.spec', return_value=self.spec):
            for flags, wanted in ((('--scope', 'current', '--item', 2), ['RAMP //OWNED/254/56/42 200 0 FORCE']),
                (('--scope', 'all'), ['RAMP //OWNED/254/56/12 10 0 FORCE', 'RAMP //OWNED/254/56/42 200 0 FORCE'])):
                client = ConnectedClient(*(reply('200 OK') for _ in wanted))
                with patch('cbus_toolkit.cgate.CGateClient', return_value=client): result = self.invoke(self.broadcast(*flags))
                self.assertEqual(client.commands, wanted); self.assertTrue(result['complete'])
                self.assertFalse(result['saved']); self.assertFalse(result['physical_device_verified'])
            client = ConnectedClient(reply('401 Owned rejection'), reply('200 OK'))
            with patch('cbus_toolkit.cgate.CGateClient', return_value=client): result = self.invoke(self.broadcast('--scope', 'all'), 1)
            self.assertEqual([r['status'] for r in result['items']], ['rejected', 'accepted'])
            self.assertTrue(result['sequence_finished']); self.assertEqual(len(client.commands), 2)
            self.assertEqual(result['automatic_retries'], 0)

    def test_bad_source_cache_route_and_selection_never_connect_or_send(self):
        class NoConnect(ConnectedClient):
            def __enter__(self): raise AssertionError('Invalid input must not connect')
        with patch('cbus_toolkit.edlt_global_cli.spec', return_value=self.spec), \
                patch('cbus_toolkit.cgate.CGateClient', side_effect=lambda *a, **kw: NoConnect()):
            for flags, message in ((('--scope', 'current'), 'explicit --item'),
                (('--scope', 'all', '--item', 1), 'only valid'), (('--scope', 'current', '--item', 99), 'Current item'),
                (('--scope', 'all', '--network', '//OWNED/0254'), 'explicit live network')):
                self.assertIn(message, self.invoke(self.broadcast(*flags), 1)['error'])
            self.source.write_text('{"x":1,"x":2}')
            self.assertIn('Duplicate JSON key', self.invoke(self.broadcast('--scope', 'all'), 1)['error'])
            self.source.write_text(json.dumps(self.session.values())); self.cache.write_text('[NaN]')
            self.assertIn('Non-finite JSON', self.invoke(self.broadcast('--scope', 'all'), 1)['error'])

    def test_incomplete_capture_reports_partial_state_without_staging_or_saving(self):
        for failed in (get(42, 'invalid'), reply('300 //OWNED/254/56/42: Other=100'), TimeoutError('lost read')):
            with self.subTest(failure=str(failed)):
                client = ConnectedClient(get(12, 37), failed)
                editor = SceneCaptureCLIEditor(self.spec, client, network='//OWNED/254')
                self.session.set = Mock(side_effect=AssertionError('Incomplete capture cannot stage'))
                self.session.save_to_source = Mock()
                @contextmanager
                def session_context(): yield self.session
                with patch.object(cli, '_edlt_scene_capture', return_value=editor), \
                        patch('cbus_toolkit.cgate.CGateClient', return_value=client), \
                        patch('cbus_toolkit.programming.Programmer', return_value=SimpleNamespace(load=Mock(return_value=session_context()))):
                    result = self.invoke(self.capture(), 1)
                evidence = result['edlt_scene_live_evidence']; capture = evidence['live_capture']
                self.assertFalse(capture['complete']); self.assertFalse(capture['state']['complete'])
                self.assertEqual(capture['state']['scenes'][0]['items'][0]['level'], 37)
                self.assertFalse(evidence['saved']); self.assertFalse(evidence['save_attempted'])
                self.assertEqual(evidence['attempted_parameters'], [])
                self.session.set.assert_not_called(); self.session.save_to_source.assert_not_called()
                self.assertEqual(len(client.commands), 2)

    def test_capture_dry_run_and_finalize_faults_retain_live_and_pp_evidence(self):
        class Refusing(KeyboardInterrupt):
            def __setattr__(self, name, value):
                if name.startswith('edlt_'): raise SystemExit('Cannot attach evidence')
                super().__setattr__(name, value)
        for phase in ('dry_run', 'configure', 'readback', 'save', 'cleanup', 'connection_cleanup'):
            for kind in ((OSError,) if phase == 'dry_run' else (OSError, Refusing)):
                with self.subTest(phase=phase, kind=kind.__name__):
                    client = Client(get(12, 37), get(42, 203)); error = kind('Owned fault')
                    session = Session(self.spec); session.current = dict(self.session.current)
                    editor = SceneCaptureCLIEditor(self.spec, client, network='//OWNED/254')
                    original, completed = editor.configure, []
                    if phase == 'configure': session.set = Mock(side_effect=error)
                    def configure(*args, **kwargs):
                        result = original(*args, **kwargs); completed.append(result)
                        if phase == 'readback': session.values = Mock(side_effect=error)
                        return result
                    session.save_to_source = Mock(side_effect=error if phase == 'save' else None, return_value=object())
                    @contextmanager
                    def context():
                        yield session
                        if phase == 'cleanup': raise error
                    @contextmanager
                    def connection():
                        yield client
                        if phase == 'connection_cleanup': raise error
                    with patch.object(editor, 'configure', side_effect=configure), \
                            patch.object(cli, '_edlt_scene_capture', return_value=editor), \
                            patch('cbus_toolkit.cgate.CGateClient', return_value=connection()), \
                            patch('cbus_toolkit.programming.Programmer', return_value=SimpleNamespace(load=Mock(return_value=context()))):
                        result = self.invoke(self.capture(*(['--dry-run'] if phase == 'dry_run' else [])),
                            0 if phase == 'dry_run' else 130 if isinstance(error, KeyboardInterrupt) else 1)
                    if phase == 'dry_run':
                        self.assertFalse(result['saved']); self.assertTrue(result['verified'])
                        self.assertTrue(session.calls); session.save_to_source.assert_not_called()
                        self.assertTrue(result['live_capture']['complete'])
                    else:
                        evidence = result['edlt_scene_live_evidence']
                        self.assertEqual(evidence['failure_phase'], phase); self.assertTrue(evidence['live_capture']['complete'])
                        self.assertEqual(evidence['saved'], phase in ('cleanup', 'connection_cleanup'))
                        self.assertEqual(evidence['save_outcome_uncertain'], phase == 'save')
                        if phase in ('configure', 'readback'): session.save_to_source.assert_not_called()
                    self.assertEqual(client.commands, ['GET //OWNED/254/56/12 Level', 'GET //OWNED/254/56/42 Level'])

    def test_broadcast_transport_and_socket_cleanup_preserve_attempts_and_interrupts(self):
        class Refusing(KeyboardInterrupt):
            def __setattr__(self, name, value): raise SystemExit('No attachment')
        with patch('cbus_toolkit.edlt_global_cli.spec', return_value=self.spec):
            client = ConnectedClient(TimeoutError('lost ACK'), reply('200 OK'))
            with patch('cbus_toolkit.cgate.CGateClient', return_value=client): result = self.invoke(self.broadcast('--scope', 'all'), 1)
            self.assertFalse(result['sequence_finished']); self.assertTrue(result['transport_outcome_uncertain'])
            self.assertEqual(len(client.commands), 1)
            for error in (OSError('close failed'), Refusing('first interruption')):
                class FailingClose(ConnectedClient):
                    def __exit__(self, *args): raise error
                client = FailingClose(reply('200 OK'), reply('200 OK'))
                with patch('cbus_toolkit.cgate.CGateClient', return_value=client):
                    result = self.invoke(self.broadcast('--scope', 'all'), 130 if isinstance(error, KeyboardInterrupt) else 1)
                evidence = result['edlt_scene_live_evidence']
                self.assertEqual(evidence['failure_phase'], 'connection_cleanup')
                self.assertEqual([r['status'] for r in evidence['items']], ['accepted', 'accepted'])
                self.assertEqual(len(client.commands), 2); self.assertEqual(evidence['automatic_retries'], 0)

    @unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST') and os.environ.get('CBUS_UNITSPEC_DIR'), 'Set owned C-Gate and exact specification')
    def test_native_capture_preview_save_reload_and_broadcast_receiver(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.edlt import _render
        from cbus_toolkit.edlt_scene_manager import EdltSceneManager
        from cbus_toolkit.native import NativeProjects, NativeDatabase
        from cbus_toolkit.programming import Programmer
        from cbus_toolkit.simulator import PCISimulator
        from cbus_toolkit.unitspec import UnitSpecStore
        host, port = os.environ['CBUS_CGATE_TEST_HOST'], int(os.environ.get('CBUS_CGATE_TEST_PORT', '20033'))
        project = 'LC'+uuid4().hex[:6].upper(); live_network = '//'+project+'/254'; db_network = '//'+project+'/253'
        source = '/db'+db_network+'/p/20'; sim_state = self.folder/'receiver.json'
        groups = {key: 0 for key in PCISimulator(profile='synthetic').lighting.groups}
        groups.update({(56, 12): 0, (56, 42): 0})
        simulator = PCISimulator(profile='synthetic', state_path=sim_state, response_delay=0.01, lighting_groups=groups)
        spec = UnitSpecStore(os.environ['CBUS_UNITSPEC_DIR']).load('KEYGL5.xml'); manager = EdltSceneManager(spec)
        def call(*args, status=0):
            process = subprocess.run([sys.executable, '-m', 'cbus_toolkit', *map(str, args)], capture_output=True, text=True, timeout=60)
            self.assertEqual(process.returncode, status, process.stdout+process.stderr)
            return json.loads(process.stdout or process.stderr)
        def eventually(predicate):
            deadline = time.monotonic()+8
            while not predicate():
                self.assertLess(time.monotonic(), deadline, 'Owned receiver did not reach its expected state'); time.sleep(0.02)
        with simulator.running('127.0.0.1', 0) as (_, sim_port), CGateClient(host, port, timeout=30) as client:
            projects, database = NativeProjects(client), NativeDatabase(client); projects.operation('new', project)
            opened = False
            try:
                database.create_network(project, 253, 'Scene_DB', 'Cni', '127.0.0.1:1')
                database.create_network(project, 254, 'Scene_Live', 'Cni', f'127.0.0.1:{sim_port}')
                database.create_unit(db_network, 20, 'eDLT', 'KEYGL5', '5.5.00', catalog_number='5055EDL')
                with Programmer(client).load(db_network, source) as session:
                    current = manager.snapshot(session.values()); seed = manager.snapshot(vectors()['input'])
                    seed.update(Project=project, UnitAddress=(20,), UnitName='LIVECLI')
                    for name, value in seed.items():
                        if value != current[name]: session.set(name, _render(value))
                    session.save_to_source()
                client.command(f'DBADDSAFE {live_network} Application 56 Lighting')
                for group in (12, 42): client.command(f'DBADDSAFE {live_network}/56 Group {group} Owned{group}')
                projects.operation('save', project); client.command('NET LOAD DB '+project)
                client.command('NET OPEN '+live_network); opened = True
                deadline = time.monotonic()+25
                while not any('state=ok' in line for line in client.command('GET '+live_network+' state').lines):
                    self.assertLess(time.monotonic(), deadline); time.sleep(0.1)
                for group, level in ((12, 37), (42, 203)):
                    client.command(f'RAMP {live_network}/56/{group} {level} 0 FORCE')
                    eventually(lambda: simulator.lighting.level(56, group) == level)
                    eventually(lambda: client.command(f'GET {live_network}/56/{group} Level').final.endswith(f'Level={level}'))
                args = ('cgate', '--host', host, '--port', port, '--timeout', 30, 'unit', '--lock-address', db_network, '--source', source)
                flags = self.flags(live_network); original = call(*args, 'show')
                preview = call(*args, '--dry-run', 'edlt-scene-capture', *flags)
                self.assertFalse(preview['saved']); self.assertTrue(preview['live_capture']['complete'])
                self.assertEqual(call(*args, 'show'), original)
                saved = call(*args, 'edlt-scene-capture', *flags)
                self.assertTrue(saved['saved']); self.assertEqual(saved['parameters'], preview['parameters'])
                self.assertEqual(len(saved['parameters']), 874)
                self.assertIn('database destinations only', call(*args, '--destination', live_network+'/p/20', 'edlt-scene-capture', *flags, status=1)['error'])
                self.source.unlink(); call(*args, 'export', self.source)
                for group in (12, 42):
                    client.command(f'RAMP {live_network}/56/{group} 0 0 FORCE')
                    eventually(lambda: simulator.lighting.level(56, group) == 0)
                result = call('cgate', '--host', host, '--port', port, '--timeout', 30, 'edlt-scene-broadcast', self.source, *flags, '--scope', 'all')
                self.assertTrue(result['complete']); self.assertFalse(result['saved'])
                eventually(lambda: simulator.lighting.level(56, 12) == 37 and simulator.lighting.level(56, 42) == 203)
                self.assertEqual(PCISimulator(profile='synthetic', state_path=sim_state).lighting.snapshot(), simulator.lighting.snapshot())
                client.command('NET CLOSE '+live_network); opened = False
                for action in ('save', 'close', 'load'): projects.operation(action, project)
                self.assertEqual(call(*args, 'show'), saved['parameters'])
                self.assertTrue(any('state=new' in line for line in client.command('GET '+db_network+' state').lines))
                self.assertFalse([row for row in simulator.wire_log if row.get('reason')])
            finally:
                if opened: client.command('NET CLOSE '+live_network)
                try: projects.operation('close', project)
                finally: projects.operation('delete', project)
