"""Standalone IOPE parser, offline envelopes and save-boundary regression tests."""
import json
import io
from contextlib import redirect_stderr
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
import xml.etree.ElementTree as ET

from cbus_toolkit import iope_workflow_cli as cli
from cbus_toolkit.iope_output_settings import IopeOutputSettings, LAYOUTS, PROFILES
from cbus_toolkit.cgate import CGateResponse
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec
from test_macros import Session


def fixture():
    params = {}
    defaults = {'MinDimmingLevel': [0]*4, 'MaxDimmingLevel': [255]*2,
                'RestrikeChannel': [0]*4, 'RestrikeDelay': [1]}
    for name, (kind, address, size, bits, bit, skip) in LAYOUTS.items():
        fields = {'Name': name, 'Type': kind, 'Address': str(address), 'ArraySize': str(size),
                  'BitSize': str(bits), 'BitAddress': str(bit), 'ArraySkip': str(skip),
                  'DefaultValue': ' '.join(map(str, defaults[name])), 'MinValue': '0',
                  'MaxValue': str((1 << bits)-1)}
        params[name] = ParameterSpec(name, kind, 'synthetic.xml', fields)
    return UnitSpec('IOPE2C4.xml', {'Type': 'IOPE2C4'}, ('synthetic.xml',), params)


def session():
    pp = Session(fixture())
    pp.unit_type, pp.firmware, pp.catalog_number = 'IOPE2C4', '1.2.00', '5752PP/2R/2D'
    pp.__enter__ = lambda: pp
    return pp


class Context:
    def __init__(self, pp): self.pp = pp
    def __enter__(self): return self.pp
    def __exit__(self, *args): return False


def args(*extra):
    return cli.parser().parse_args(['--spec-dir', '/synthetic', 'output', 'database',
        '--host', '127.0.0.1', '--port', '1', '--source', '/db//TEST/254/p/20',
        '--lock-address', '//TEST/254', *extra])


class IopeWorkflowCliTest(unittest.TestCase):
    def test_refuse_physical_noncanonical_cross_network_before_client(self):
        for source, lock in [('//TEST/254/p/20','//TEST/254'),('/db//TEST/0254/p/20','//TEST/254'),
                             ('/db//TEST/256/p/20','//TEST/256'),('/db//TEST/254/p/20','//OTHER/254')]:
            selected = args('--show')
            selected.source, selected.lock_address = source, lock
            factory = MagicMock()
            with self.subTest(source=source, lock=lock), self.assertRaises(ValueError):
                cli.run(selected, factory)
            factory.assert_not_called()
        for options in (('--plan', 'missing'), ('--show', '--dry-run')):
            factory = MagicMock()
            with self.assertRaises(ValueError): cli.run(args(*options), factory)
            factory.assert_not_called()

    def test_duplicate_oversized_nonfinite_and_identity_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'input.json'
            for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'x'*(cli.LIMIT+1), b''):
                path.write_bytes(raw)
                with self.subTest(raw=raw[:40]), self.assertRaises(ValueError): cli.read_json(path)
        for raw in ({}, {'unit_type':'IOPE2C4','firmware':'1.3.00','catalog_number':'5752PP/2R/2D'},
                    {'unit_type':'IOPE2C4','firmware':'1.2.00','catalog_number':'5752PP/2R'}):
            with self.assertRaises(ValueError): cli._identity(raw)
        with self.assertRaises(ValueError): cli._edits({'channels':{'01':{'min_percent':50}}})

    def test_new_families_and_numbered_editor_options(self):
        for family in ('logic', 'join-recovery', 'block-timer', 'join-groups', 'scene-selectors', 'scene-levels'):
            with self.subTest(family=family):
                selected = cli.parser().parse_args([family, 'show', 'snapshot.json'])
                self.assertEqual(selected.family, family)
                self.assertEqual(selected.action, 'show')
        edits = {'channels': {'1': {'logic_groups': [1, 3]}},
                 'logic_groups': {'4': {'group_address': 20}}}
        result = cli._edits(edits)
        self.assertEqual(result['channels'], {1: {'logic_groups': [1, 3]}})
        self.assertEqual(result['logic_groups'], {4: {'group_address': 20}})
        self.assertIn('1', edits['channels'])
        for field in ('channels', 'logic_groups'):
            for key in ('0', '5', '01', '+1', '1.0'):
                with self.subTest(field=field, key=key), self.assertRaises(ValueError):
                    cli._edits({field: {key: {}}})

    def test_group_cache_checked_before_staging_and_save_for_all_families(self):
        # Check the shared persistence boundary separately from source-pinned editors.
        cache = {'applications': [{'address': 56, 'groups': [20]}]}
        for family in ('environment', 'logic', 'join-recovery', 'block-timer', 'join-groups', 'scene-selectors', 'scene-levels'):
            for fail_at in (1, 2):
                with self.subTest(family=family, fail_at=fail_at):
                    pp = session()
                    pp.save_to_source = MagicMock()
                    editor = MagicMock()
                    editor.apply.return_value = {'saved': False}
                    plan = SimpleNamespace(changes={'MinDimmingLevel': [0]*4},
                                           details={'options': {'group_cache': cache}})
                    selected = args('--plan', 'unused', '--exclusive-project')
                    selected.family = family
                    checks = [ValueError('stale native group evidence')] if fail_at == 1 else [None, ValueError('stale native group evidence')]
                    with patch.object(cli, '_closed', return_value=ET.Element('Network')), \
                            patch.object(cli, '_check_group_cache', side_effect=checks) as check, \
                            patch('cbus_toolkit.programming.Programmer') as programmer, \
                            patch('cbus_toolkit.native.NativeProjects') as projects:
                        programmer.return_value.load.return_value = Context(pp)
                        with self.assertRaisesRegex(ValueError, 'stale native'):
                            cli.database(selected, MagicMock(), editor=editor, plan=plan)
                        self.assertEqual(check.call_count, fail_at)
                        self.assertEqual(editor.apply.call_count, fail_at - 1)
                        pp.save_to_source.assert_not_called()
                        projects.return_value.operation.assert_not_called()

    def test_native_xml_and_positive_metadata(self):
        xml = '<Installation><Project><Address>TEST</Address><Network><Address>254</Address><Application><Address>56</Address><Group><Address>20</Address></Group></Application></Network></Project></Installation>'
        client = MagicMock()
        client.command.return_value = CGateResponse(('347-'+xml,'344 End XML'), '344 End XML',344)
        doc = cli._project_document(client,'TEST')
        cli._check_group_cache(doc.find('Network'), {'applications':[{'address':56,'groups':[20]}]})
        with self.assertRaisesRegex(ValueError, 'current native'):
            cli._check_group_cache(doc.find('Network'), {'applications':[{'address':56,'groups':[21]}]})
        with self.assertRaises(ValueError): cli._project_document(client,'OTHER')

    def test_complete_action_inventory_uses_native_addresses(self):
        network = ET.fromstring('<Network><Application><Address>202</Address><Group><Address>20</Address><Level><Address>10</Address><Value>99</Value></Level><Level><Address>11</Address><Value>99</Value></Level></Group></Application></Network>')
        cache = {'applications': [{'address': 202, 'groups': [20]}],
                 'action_selectors': [{'application': 202, 'group': 20, 'addresses': [10, 11]}]}
        # Source serializes Level Address; distinct values/labels are not dependencies.
        cli._check_group_cache(network, cache)
        for addresses in ([10], [10, 11, 12], [99]):
            bad = {**cache, 'action_selectors': [{'application': 202, 'group': 20,
                                                 'addresses': addresses}]}
            with self.subTest(addresses=addresses), self.assertRaisesRegex(ValueError, 'complete native'):
                cli._check_group_cache(network, bad)
        group = network.find('Application/Group')
        group.append(ET.fromstring('<Level><Address>10</Address><Value>100</Value></Level>'))
        with self.assertRaisesRegex(ValueError, 'Duplicate native action'):
            cli._check_group_cache(network, cache)
        group.remove(group[-1])
        cache['action_selectors'][0]['group'] = 21
        with self.assertRaisesRegex(ValueError, 'missing'):
            cli._check_group_cache(network, cache)

    def test_closed_state_and_selected_network_checks(self):
        project = ET.fromstring('<Project><Network><Address>254</Address></Network></Project>')
        with patch.object(cli,'_project_document',return_value=project), patch('cbus_toolkit.addressing.NetworkAddressing') as guard:
            guard.return_value._runtime.return_value = [('InterfaceState','closed'),('TargetInterfaceState','closed'),('SyncState','idle')]
            self.assertEqual(cli._closed(MagicMock(),'TEST','//TEST/254').findtext('Address'),'254')
            with self.assertRaisesRegex(ValueError,'missing'): cli._closed(MagicMock(),'TEST','//TEST/253')
            guard.return_value._runtime.return_value = [('InterfaceState','running')]
            with self.assertRaisesRegex(ValueError,'closed'): cli._closed(MagicMock(),'TEST','//TEST/254')

    def test_apply_dry_run_and_uncertain_save_are_never_retried(self):
        editor = IopeOutputSettings(fixture())
        for mode in ('dry-run','success','pp-failure','project-failure','reload-mismatch','pp-interrupt','project-interrupt'):
            with self.subTest(mode=mode):
                pp = session()
                plan = editor.plan(pp.values(), identity=(pp.unit_type,pp.firmware,pp.catalog_number),
                                   channels={1:{'min_percent':50}})
                pp.save_to_source = MagicMock(side_effect=(RuntimeError('uncertain save') if mode=='pp-failure' else KeyboardInterrupt() if mode=='pp-interrupt' else None))
                selected = args('--plan','unused','--exclusive-project', *(['--dry-run'] if mode=='dry-run' else []))
                reload = session() if mode=='reload-mismatch' else pp
                with patch.object(cli,'_closed',return_value=ET.Element('Network')), \
                        patch('cbus_toolkit.programming.Programmer') as programmer, \
                        patch('cbus_toolkit.native.NativeProjects') as projects:
                    programmer.return_value.load.side_effect = [Context(pp), Context(reload)]
                    projects.return_value.operation.return_value.code = 200
                    if mode=='project-failure': projects.return_value.operation.side_effect=RuntimeError('project failed')
                    if mode=='project-interrupt': projects.return_value.operation.side_effect=SystemExit(2)
                    if mode in ('pp-failure','project-failure','reload-mismatch','pp-interrupt','project-interrupt'):
                        with self.assertRaises(cli.PersistenceError) as caught:
                            cli.database(selected,MagicMock(),editor=editor,plan=plan)
                        self.assertFalse(caught.exception.evidence['saved'])
                        self.assertTrue(caught.exception.evidence['outcome_uncertain'])
                        self.assertFalse(caught.exception.evidence['automatic_retry_performed'])
                    else:
                        result = cli.database(selected,MagicMock(),editor=editor,plan=plan)
                        self.assertEqual(result['saved'],mode=='success')
                        self.assertEqual(result['fresh_reload_verified'],mode=='success')
                    self.assertEqual(pp.save_to_source.call_count,0 if mode=='dry-run' else 1)
                    self.assertEqual(projects.return_value.operation.call_count,0 if mode in ('dry-run','pp-failure','pp-interrupt') else 1)

    def test_registered_shared_cli_keeps_uncertain_save_evidence(self):
        from cbus_toolkit import cli as shared
        error = cli.PersistenceError(KeyboardInterrupt(), {
            'saved': False, 'pp_save_attempted': True, 'outcome_uncertain': True})
        selected = args('--plan', 'unused', '--exclusive-project')
        selected.area, selected.compact = 'iope-workflow', False
        with patch.object(shared, 'build_parser') as parser, patch.object(shared, 'run', side_effect=error):
            parser.return_value.parse_args.return_value = selected
            output = io.StringIO()
            with redirect_stderr(output): self.assertEqual(shared.main([]), 1)
        result = json.loads(output.getvalue())
        self.assertTrue(result['outcome_uncertain'])
        self.assertTrue(result['pp_save_attempted'])
        self.assertFalse(result['saved'])

    def test_offline_plan_and_forged_plan_refused_before_client(self):
        pp = session()
        editor = IopeOutputSettings(fixture())
        snapshot = {'format':'cbus-cli-parameters-v1','unit_type':pp.unit_type,'firmware':pp.firmware,
                    'catalog_number':pp.catalog_number,'parameters':pp.values()}
        with tempfile.TemporaryDirectory() as folder:
            path, edits, saved = [Path(folder)/name for name in ('snapshot.json','edits.json','plan.json')]
            path.write_text(json.dumps(snapshot)); edits.write_text(json.dumps({'channels':{'1':{'min_percent':50}}}))
            selected = cli.parser().parse_args(['--spec-dir',folder,'output','plan',str(path),'--edits',str(edits)])
            from cbus_toolkit import iope_output_settings as module
            with patch.object(cli,'_editor',return_value=(module,editor)):
                result, status = cli.run(selected)
                self.assertEqual(status,0)
                self.assertEqual(result['changes']['MinDimmingLevel'],[127,0,0,0])
                edits.write_text(json.dumps({'unknown_control':True}))
                with self.assertRaises(ValueError): cli.run(selected)
                result['changes']['RestrikeDelay']=[3]
                saved.write_text(json.dumps(result))
                factory=MagicMock()
                with self.assertRaisesRegex(ValueError,'canonical'):
                    cli.run(args('--plan',str(saved),'--exclusive-project'),factory)
                factory.assert_not_called()


if __name__ == '__main__': unittest.main()
