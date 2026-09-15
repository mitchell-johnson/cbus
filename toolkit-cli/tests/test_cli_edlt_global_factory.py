"""Explicit factory Global CLI inputs, retained evidence and owned DB saves."""
from contextlib import contextmanager, redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from cbus_toolkit import cli, edlt_global_cli
from cbus_toolkit.edlt_global_programming import EdltGlobalProgramming, CATEGORIES
from cbus_toolkit.edlt_reset import EdltResetControls
from tests.test_edlt_global_factory import fixture, vectors


class FactoryGlobalCLITests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture(); self.data = vectors(); self.row = self.data['cases'][0]
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.source = self.folder/'source.json'; self.metadata = self.folder/'metadata.json'
        self.context = self.folder/'context.json'
        self.document = {'format': 'cbus-cli-parameters-v1', 'unit_type': 'KEYGL5',
            'firmware': '5.5.00', 'catalog_number': '5055EDL', 'parameters': self.row['raw_input']}
        self.context_value = {key: self.row[key] for key in ('form_project', 'cached_network_project')}
        self.context_value['source'] = self.row['source_path']
        self.restore_files()

    def restore_files(self):
        self.source.write_text(json.dumps(self.document))
        self.metadata.write_text(json.dumps(self.data['metadata']))
        self.context.write_text(json.dumps(self.context_value))

    def arguments(self, *, native=False):
        head = ('cgate', 'edlt-global') if native else ('edlt', 'global-plan')
        result = (*head, str(self.source), '--metadata', str(self.metadata), '--factory-context', str(self.context))
        if native:
            result += ('--source-database', self.row['source_path'], '--destination', self.row['destination'], '--exclusive-project')
        return result

    def invoke(self, arguments, status=0):
        out, error = io.StringIO(), io.StringIO()
        with patch('cbus_toolkit.edlt_global_cli.spec', return_value=self.spec), redirect_stdout(out), redirect_stderr(error):
            actual = cli.main(list(map(str, arguments)))
        self.assertEqual(actual, status, out.getvalue() + error.getvalue())
        return json.loads(out.getvalue() or error.getvalue())

    def test_original_factory_literal_payload_all_empty_and_exact_order(self):
        with patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('Offline cannot connect')):
            for categories, mask in (((), 0), (tuple(CATEGORIES), 15)):
                flags = tuple(part for category in categories for part in ('--category', category))
                result = self.invoke((*self.arguments(), *flags))
                original = next(row for row in self.row['workers'] if row['mask'] == mask)
                self.assertEqual([[row['parameter'], row['native_value']] for row in result['ordered_payload']], original['ordered_payload'])
                self.assertTrue(result['factory_model_preparation_applied'])
                self.assertTrue(result['factory_literal_values_preserved'])
                source = result['source']['factory_preparation']
                self.assertEqual(source['expected_raw'], self.document['parameters'])
                self.assertEqual(source['raw_phases']['after-reset']['raw']['NavWidgetType'], '0xFF')
                self.assertEqual(source['raw_phases']['after-global-tab-removal']['raw']['NavWidgetType'], '0x0')
                self.assertEqual(source['raw_phases']['final']['raw']['Project'], 'NetPrj TAIL')
                self.assertFalse(source['third_load_applied']); self.assertFalse(result['saved'])
            order = self.folder/'order.json'; order.write_text(json.dumps(list(self.row['raw_input'])))
            explicit = self.invoke((*self.arguments(), '--parameter-order', order))
            self.assertEqual(explicit['ordered_payload'], self.invoke(self.arguments())['ordered_payload'])

    def test_strict_raw_context_and_cache_inputs_fail_before_connect(self):
        bad_documents = [self.row['raw_input'], {**self.document, 'extra': True},
            {**self.document, 'format': 'cbus-edlt-raw-parameters-v1'},
            {**self.document, 'firmware': '5.4.00'},
            {**self.document, 'parameters': {**self.row['raw_input'], 'NavWidgetType': [255]}},
            {**self.document, 'parameters': dict(reversed(list(self.row['raw_input'].items())))},
            {**self.document, 'parameters': {**self.row['raw_input'], 'FontStyle': '0x2'}}]
        with patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('Invalid inputs cannot connect')) as connect:
            for document in bad_documents:
                self.restore_files(); self.source.write_text(json.dumps(document))
                self.invoke(self.arguments(native=True), 1)
            for context in ({}, {**self.context_value, 'extra': 1}, {**self.context_value, 'form_project': True},
                            {**self.context_value, 'source': '//BAD/0254/p/20'},
                            {**self.context_value, 'cached_network_project': 'OVERLONG9'}):
                self.restore_files(); self.context.write_text(json.dumps(context))
                self.invoke(self.arguments(native=True), 1)
            for text in ('{"source":"a","source":"b"}', '{"source":NaN}', ' ' * (16 * 1024 + 1)):
                self.restore_files(); self.context.write_text(text)
                self.invoke(self.arguments(native=True), 1)
            self.restore_files(); self.metadata.write_text(json.dumps(self.data['metadata']['lifecycle']))
            self.invoke(self.arguments(native=True), 1)
            self.restore_files(); self.metadata.write_text('{"format":"a","format":"b"}')
            self.invoke(self.arguments(native=True), 1)
            connect.assert_not_called()

    def test_native_source_context_match_and_original_order_are_preconnection_guards(self):
        args = list(self.arguments(native=True)); index = args.index('--source-database')
        with patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('Invalid inputs cannot connect')) as connect:
            for source in (None, '//OTHER/254/p/20', self.row['source_path'].lower(), self.row['destination']):
                changed = args[:]
                if source is None: del changed[index:index + 2]
                else: changed[index + 1] = source
                result = self.invoke(changed, 1)
                self.assertIn('exact factory context source', result['error'])
            order = self.folder/'order.json'; order.write_text(json.dumps(list(reversed(self.row['raw_input']))))
            self.assertIn('cannot reorder', self.invoke((*args, '--parameter-order', order), 1)['error'])
            self.invoke(args[:-1], 1)
            self.invoke((*args, '--dry-run', '--backup-project', 'OWNEDBK'), 1)
            connect.assert_not_called()

    def test_factory_preparation_error_and_unattachable_interrupt_evidence(self):
        class RejectEvidence(KeyboardInterrupt):
            def __setattr__(self, name, value):
                if name.startswith('edlt_'): raise SystemExit('Attachment rejected')
                super().__setattr__(name, value)
        for native in (False, True):
            error = RejectEvidence('Owned interrupted preparation')
            with patch.object(EdltResetControls, '_factory_transition_steps', side_effect=error), \
                 patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('Preparation must finish before connecting')):
                result = self.invoke(self.arguments(native=native), 130)
                evidence = result[edlt_global_cli.EVIDENCE]
                self.assertEqual(evidence['stage'], 'factory_reset')
                self.assertEqual(evidence['cli_failure_stage'], 'factory_preparation')
                self.assertFalse(evidence['complete']); self.assertFalse(evidence['saved'])
                self.assertIn('factory_reset_evidence', evidence)
        for error in (RejectEvidence('same object'), SystemExit('same object')):
            args = cli.build_parser().parse_args(list(self.arguments()))
            with patch('cbus_toolkit.edlt_global_cli.spec', return_value=self.spec), \
                 patch.object(EdltResetControls, '_factory_transition_steps', side_effect=error):
                with self.assertRaises(BaseException) as caught: edlt_global_cli.offline(args)
            self.assertIs(caught.exception, error)
            self.assertFalse(edlt_global_cli.error_payload(error, args)[edlt_global_cli.EVIDENCE]['complete'])
        class Unprintable(RuntimeError):
            def __str__(self): raise SystemExit('Do not replace original')
        error = Unprintable()
        with patch.object(EdltResetControls, '_factory_transition_steps', side_effect=error):
            result = self.invoke(self.arguments(), 1)
            self.assertIn('Unprintable', result['error'])
            self.assertFalse(result[edlt_global_cli.EVIDENCE]['complete'])

    def test_bridge_failure_does_not_reuse_success_as_complete_evidence(self):
        error = RuntimeError('Owned bridge failure')
        with patch.object(EdltGlobalProgramming, 'prepare_factory_source', side_effect=error):
            result = self.invoke(self.arguments(), 1)
        evidence = result[edlt_global_cli.EVIDENCE]
        self.assertFalse(evidence['complete']); self.assertEqual(evidence['cli_failure_stage'], 'factory_source_bridge')

    def test_second_preparation_and_connection_cleanup_keep_evidence(self):
        class RejectEvidence(KeyboardInterrupt):
            def __setattr__(self, name, value):
                if name.startswith('edlt_'): raise SystemExit('Attachment rejected')
                super().__setattr__(name, value)
        original = EdltResetControls._factory_transition_steps; calls = []; error = RejectEvidence('Second preparation')
        def steps(editor, *args):
            calls.append(1)
            if len(calls) == 2: raise error
            return original(editor, *args)
        @contextmanager
        def connection(*args, **kwargs): yield SimpleNamespace()
        with patch.object(EdltResetControls, '_factory_transition_steps', steps), \
             patch('cbus_toolkit.cgate.CGateClient', side_effect=connection):
            result = self.invoke(self.arguments(native=True), 130)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result[edlt_global_cli.EVIDENCE]['stage'], 'factory_reset')
        for error in (OSError('close failed'), RejectEvidence('close interrupted')):
            saved = {'complete': True, 'factory_model_preparation_applied': True,
                'targets': [{'path': self.row['destination'], 'verified_saved': True}],
                'backup_created': True, 'target_save_attempted': True}
            manager = SimpleNamespace(engine=EdltGlobalProgramming(self.spec), last_evidence=None,
                plan=Mock(return_value=object()), apply=Mock(return_value=SimpleNamespace(as_dict=lambda: saved)))
            @contextmanager
            def failing_close(*args, **kwargs):
                yield SimpleNamespace()
                raise error
            with patch('cbus_toolkit.cgate.CGateClient', side_effect=failing_close), \
                 patch('cbus_toolkit.native_global_programming.NativeEdltGlobalProgramming', return_value=manager):
                result = self.invoke(self.arguments(native=True), 130 if isinstance(error, KeyboardInterrupt) else 1)
            evidence = result[edlt_global_cli.EVIDENCE]
            self.assertEqual(evidence['targets'], saved['targets'])
            self.assertTrue(evidence['backup_created']); self.assertFalse(evidence['operation_completed'])
            self.assertEqual(evidence['failure_phase'], 'connection_cleanup')

    @unittest.skipUnless(all(os.environ.get(k) for k in ('CBUS_UNITSPEC_DIR', 'CBUS_CGATE_TEST_HOST')),
                         'Select original unit specification and owned native C-Gate')
    def test_native_factory_cli_preview_two_saves_reload_backup_and_raw_source_guard(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.edlt import _render
        from cbus_toolkit.native import NativeProjects, NativeDatabase
        from cbus_toolkit.programming import Programmer, xml_text
        from cbus_toolkit.unitspec import UnitSpecStore
        self.spec = UnitSpecStore(os.environ['CBUS_UNITSPEC_DIR']).load('KEYGL5.xml')
        host, port = os.environ['CBUS_CGATE_TEST_HOST'], int(os.environ.get('CBUS_CGATE_TEST_PORT', '20033'))
        project, backup = 'GF' + uuid4().hex[:6].upper(), 'B' + uuid4().hex[:7].upper()
        network = '//' + project + '/254'; source = network + '/p/20'; targets = [network + '/p/' + str(i) for i in (21, 22)]
        engine = EdltGlobalProgramming(self.spec); seed = engine.snapshot(self.row['raw_input'])
        sent = []
        class RecordingClient(CGateClient):
            def command(self, command, **kwargs):
                sent.append(command)
                return super().command(command, **kwargs)
        with CGateClient(host, port, timeout=30) as client:
            projects, database = NativeProjects(client), NativeDatabase(client)
            projects.operation('new', project)
            def owned_names():
                return {line.split('project=', 1)[1] for line in projects.directory().lines if 'project=' in line} & {project, backup}
            try:
                database.create_network(project, 254, 'Factory_CLI', 'Cni', '127.0.0.1:1')
                for address in (20, 21, 22):
                    database.create_unit(network, address, 'Factory_' + str(address), 'KEYGL5', '5.5.00', catalog_number='5055EDL')
                for action in ('save', 'close', 'load'): projects.operation(action, project)
                for address in (20, 21, 22):
                    values = {**seed, 'UnitAddress': (address,), 'UnitName': 'SOURCE20' if address == 20 else 'TARGET' + str(address)}
                    if address != 20:
                        for name in (name for names in CATEGORIES.values() for name in names):
                            bits = engine.codec.layout(name).bit_size; values[name] = ((seed[name][0] + 1) % (1 << bits),)
                        values.update(Project=project, SerialNumber=(address, 2, 3, 4), OverallCRC=(1, 2), GlobalParameterCRC=(3, 4),
                                      WidgetsCRC=(5, 6), StaticTextCRC=(7, 8), ScenesCheckSum=(9, 10))
                    with Programmer(client).load(network, '/db' + network + '/p/' + str(address)) as session:
                        current = engine.snapshot(session.values())
                        for name, value in values.items():
                            if value != current[name]: session.set(name, _render(value))
                        session.save_to_source()
                for action in ('save', 'close', 'load'): projects.operation(action, project)
                # Use the public export command; retain its exact field order and text.
                self.source.unlink()
                self.invoke(('cgate', '--host', host, '--port', port, 'unit', '--lock-address', network,
                             '--source', '/db' + source, 'export', self.source))
                original_file = self.source.read_bytes()
                self.context.write_text(json.dumps({'source': source, 'form_project': project, 'cached_network_project': 'NetPrj'}))
                source_xml = xml_text(database.get(source, xml=True))
                before = {path: xml_text(database.get(path, xml=True)) for path in targets}
                categories = tuple(part for name in CATEGORIES for part in ('--category', name))
                offline = self.invoke((*self.arguments(), *categories))
                args = ('cgate', '--host', host, '--port', port, '--timeout', 30, 'edlt-global', self.source,
                    '--metadata', self.metadata, '--factory-context', self.context, '--source-database', source,
                    '--destination', targets[0], '--destination', targets[1], '--exclusive-project', *categories)
                with patch('cbus_toolkit.cgate.CGateClient', RecordingClient):
                    preview = self.invoke((*args, '--dry-run'))
                    self.assertEqual(preview['payload']['ordered_payload'], offline['ordered_payload'])
                    self.assertFalse(preview['target_saved']); self.assertEqual(owned_names(), {project})
                    self.assertEqual(source_xml, xml_text(database.get(source, xml=True)))
                    for path in targets: self.assertEqual(before[path], xml_text(database.get(path, xml=True)))
                    # Same numeric state with different raw text is a stale source.
                    changed = json.loads(original_file); changed['parameters']['NavWidgetType'] = '255'
                    self.source.write_text(json.dumps(changed)); start = len(sent)
                    rejected = self.invoke((*args, '--dry-run'), 1)
                    self.assertIn('raw programming strings', rejected['error'])
                    self.assertFalse(any(c.startswith(('PP SET', 'PP SAVE', 'PROJECT COPY', 'PROJECT SAVE')) for c in sent[start:]))
                    self.source.write_bytes(original_file); start = len(sent)
                    result = self.invoke((*args, '--backup-project', backup))
                self.assertTrue(result['complete']); self.assertTrue(result['factory_model_preparation_applied'])
                self.assertTrue(result['backup_created']); self.assertTrue(all(r['verified_saved'] for r in result['targets']))
                actual = [c.split(' ', 3)[-1] for c in sent[start:] if c.startswith('PP SET')]
                wanted = [r['parameter'] + ' "' + r['native_value'] + '"' for r in offline['ordered_payload']]
                self.assertEqual(actual, wanted * 2)
                for action in ('save', 'close', 'load'): projects.operation(action, project)
                for target in preview['targets']:
                    with Programmer(client).load(network, '/db' + target['path']) as session:
                        self.assertEqual(engine.snapshot(session.values()), engine.snapshot(target['final']))
                self.assertEqual(source_xml, xml_text(database.get(source, xml=True)))
                self.assertEqual(self.source.read_bytes(), original_file)
                projects.operation('load', backup)
                for target in preview['targets']:
                    path = target['path'].replace('//' + project + '/', '//' + backup + '/', 1)
                    with Programmer(client).load('//' + backup + '/254', '/db' + path) as session:
                        self.assertEqual(engine.snapshot(session.values()), engine.snapshot(target['expected']))
                self.assertFalse(any(c.startswith(('NET OPEN', 'NET SYNC', 'NET CHECK')) for c in sent))
            finally:
                for name in (backup, project):
                    if name not in owned_names(): continue
                    try: projects.operation('close', name)
                    finally: projects.operation('delete', name)
                self.assertEqual(owned_names(), set())


if __name__ == '__main__': unittest.main()
