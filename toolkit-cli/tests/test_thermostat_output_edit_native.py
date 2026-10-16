"""Literal output Edit wire and uncertainty boundaries with a scripted client.

These checks use the actual NativeDatabase adapter but contact no endpoint.
They do not establish vendor C-Gate or original GUI execution acceptance.
"""
from contextlib import nullcontext
from dataclasses import replace
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from cbus_toolkit.cli import build_parser
from cbus_toolkit.thermostat_remote_references import (ProjectGraphSnapshot,
    RemoteApplication, RemoteCreation, RemoteGroup, RemoteGroupRename, RemoteLevel)
from cbus_toolkit.thermostat_settings import NativeThermostatSettings
from cbus_toolkit.thermostat_templates import ThermostatTemplateError
from cbus_toolkit.thermostat_templates_cli import run
from cbus_toolkit.unitspec import UnitSpecStore

from test_thermostat_output_add_native import ScriptedClient, identity, reply

APP_OID = '10000000-0000-4000-8000-000000000001'
GROUP_OID = '20000000-0000-4000-8000-000000000002'
OTHER_OID = '30000000-0000-4000-8000-000000000003'
NETWORK = '//EDIT/254'


class OutputEditNativeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.store = UnitSpecStore(self.directory)

    def manager(self, script):
        client = ScriptedClient(self, script)
        manager = NativeThermostatSettings(client, self.store)
        manager._start('independent-output-edit-materialization')
        return manager, client

    def rename(self, name='New name', *, previous='Old name', oid=GROUP_OID, explicit=True):
        return RemoteGroupRename(56, 4, oid, previous, name,
                                 'output_edit:1:HeatStage1Output', explicit)

    def plan(self, *operations, existing=True):
        groups = (RemoteGroup(56, 4, GROUP_OID, 'Old name', 'Group', ''),) if existing else ()
        app = RemoteApplication(56, APP_OID, 'Lighting', groups, '')
        graph = ProjectGraphSnapshot('EDIT', 254, 20, NETWORK+'/p/20', (), (app,),
                                     (APP_OID, GROUP_OID) if existing else (APP_OID,), '', '')
        return SimpleNamespace(network=NETWORK,
            remote=SimpleNamespace(graph=graph, graph_operations=operations))

    def prefix(self, previous='Old name'):
        return [('DBGET !'+GROUP_OID+'/OID', identity('!'+GROUP_OID, GROUP_OID)),
                ('DBGET !'+GROUP_OID+'/TagName', reply(342, '342 !'+GROUP_OID+'/TagName='+previous))]

    def fail(self, manager, plan):
        with self.assertRaises((ValueError, RuntimeError, TimeoutError)) as caught:
            manager._create_references(plan)
        with self.assertRaises(Exception):
            manager._fail(caught.exception)
        return caught.exception

    def test_explicit_edit_uses_literal_quoted_wire_and_same_identity(self):
        cases = [('éPump  Ω', r'"éPump\ \ Ω"'),
                 ('Zone "A"\\#', r'"Zone \"A\"\\#"'),
                 ('\u00a0', '"\u00a0"'),
                 ('A'*40, '"'+'A'*40+'"')]
        for name, encoded in cases:
            with self.subTest(name=name):
                script = self.prefix()+[('DBSET !'+GROUP_OID+'/TagName '+encoded, reply(200, '200 OK.'))]
                manager, client = self.manager(script)
                self.assertEqual(manager._create_references(self.plan(self.rename(name))), {})
                self.assertFalse(client.script)
                evidence = manager.last_evidence
                row, = evidence['renames']
                self.assertEqual(row['oid'], GROUP_OID)
                self.assertTrue(row['output_edit'])
                self.assertTrue(row['attempted'] and row['confirmed'])
                self.assertEqual(evidence['graph_operations'], [row])
                self.assertFalse(evidence['graph_mutation_outcome_uncertain'])
                self.assertEqual(evidence['pp_save_count'], 0)
                self.assertEqual(evidence['target_project_save_count'], 0)

    def test_edit_materialization_does_not_read_or_coerce_existing_Level_values(self):
        for value in (None, 'oops'):
            with self.subTest(value=value):
                manager, client = self.manager(self.prefix()+[
                    ('DBSET !'+GROUP_OID+'/TagName "Edited"', reply(200, '200 OK.'))])
                p = self.plan(self.rename('Edited'))
                app = p.remote.graph.applications[0]
                group = replace(app.groups[0], levels=(
                    RemoteLevel(7, value, "40000000-0000-4000-8000-000000000004", 'Opaque existing Level', ''),
                    RemoteLevel(200, None, "50000000-0000-4000-8000-000000000005", 'Missing Value at other address', '')))
                p.remote.graph = replace(p.remote.graph,
                    applications=(replace(app, groups=(group,)),))
                self.assertEqual(manager._create_references(p), {})
                self.assertFalse(client.script)
                self.assertEqual(client.commands, [
                    'DBGET !'+GROUP_OID+'/OID', 'DBGET !'+GROUP_OID+'/TagName',
                    'DBSET !'+GROUP_OID+'/TagName "Edited"'])
                self.assertEqual(p.remote.graph.applications[0].groups[0].levels,
                    group.levels)
                self.assertTrue(manager.last_evidence['renames'][0]['confirmed'])

    def test_ordinary_load_rename_retains_legacy_safe_route(self):
        manager, client = self.manager(self.prefix()+[
            ('DBSETSAFE !'+GROUP_OID+'/TagName New name', reply(200, '200 OK.'))])
        manager._create_references(self.plan(self.rename(explicit=False)))
        self.assertFalse(client.script)
        self.assertNotIn('output_edit', manager.last_evidence['renames'][0])

    def test_issued_add_identity_is_used_by_following_edit(self):
        parent = NETWORK+'/56'
        script = [('DBGET '+parent+'/OID', identity(parent, APP_OID)),
                  ('DBADD !'+APP_OID+' Group', reply(301, '301 OID='+GROUP_OID)),
                  ('DBGET !'+GROUP_OID+'/OID', identity('!'+GROUP_OID, GROUP_OID)),
                  ('DBSET !'+GROUP_OID+'/Address 4', reply(200, '200 OK.')),
                  ('DBSET !'+GROUP_OID+'/TagName "New group"', reply(200, '200 OK.')),
                  *self.prefix('New group'),
                  ('DBSET !'+GROUP_OID+'/TagName '+r'"éPump\ \ Ω"', reply(200, '200 OK.'))]
        manager, client = self.manager(script)
        rows = (RemoteCreation('Group', 56, 4, 'New group', 'output_add:1:HeatStage1Output', True),
                self.rename('éPump  Ω', previous='New group', oid='planned-group:56:4'))
        self.assertEqual(manager._create_references(self.plan(*rows, existing=False)),
                         {('Group', 56, 4): GROUP_OID})
        self.assertFalse(client.script)
        self.assertEqual([r['action'] for r in manager.last_evidence['graph_operations']], ['create', 'rename'])
        self.assertEqual(manager.last_evidence['renames'][0]['oid'], GROUP_OID)

    def test_repeated_edits_preserve_intermediate_old_name_checks_and_writes(self):
        script = self.prefix()+[('DBSET !'+GROUP_OID+'/TagName "Temporary"', reply(200, '200 OK.')),
            *self.prefix('Temporary'), ('DBSET !'+GROUP_OID+'/TagName "Old name"', reply(200, '200 OK.'))]
        manager, client = self.manager(script)
        manager._create_references(self.plan(self.rename('Temporary'),
            self.rename('Old name', previous='Temporary')))
        self.assertFalse(client.script)
        self.assertEqual([r['name'] for r in manager.last_evidence['renames']], ['Temporary', 'Old name'])
        self.assertTrue(all(r['confirmed'] for r in manager.last_evidence['renames']))

    def test_stale_identity_or_previous_name_refuses_before_any_write(self):
        prefixes = [[('DBGET !'+GROUP_OID+'/OID', identity('!'+GROUP_OID, OTHER_OID))],
                    self.prefix('Changed elsewhere'),
                    [self.prefix()[0], ('DBGET !'+GROUP_OID+'/TagName', reply(342,
                        '342 !'+GROUP_OID+'/TagName=Old name', '342 duplicate'))]]
        for script in prefixes:
            with self.subTest(script=script):
                manager, client = self.manager(script)
                with self.assertRaises(ThermostatTemplateError):
                    manager._create_references(self.plan(self.rename()))
                self.assertFalse(client.script)
                self.assertFalse(any(c.startswith('DBSET') for c in client.commands))
                self.assertFalse(manager.last_evidence['graph_mutation_attempted'])

    def test_protocol_controls_refuse_before_reads_or_writes(self):
        for control in ('\x00', '\t', '\r', '\n', '\x1f', '\x7f'):
            with self.subTest(control=repr(control)):
                manager, client = self.manager([])
                with self.assertRaisesRegex(ValueError, 'control characters'):
                    manager._create_references(self.plan(self.rename('A'+control+'B')))
                self.assertEqual(client.commands, [])
                self.assertFalse(manager.last_evidence['graph_mutation_attempted'])

    def test_lost_or_nonterminal_success_stops_without_replay_or_later_rename(self):
        for response in (TimeoutError('lost successful reply'), reply(200, '200 OK.', '200 duplicate'),
                         reply(301, '301 OID='+GROUP_OID)):
            with self.subTest(response=response):
                script = self.prefix()+[('DBSET !'+GROUP_OID+'/TagName "Temporary"', response)]
                manager, client = self.manager(script)
                self.fail(manager, self.plan(self.rename('Temporary'), self.rename('Final', previous='Temporary')))
                self.assertFalse(client.script)
                self.assertEqual(sum(c.startswith('DBSET ') for c in client.commands), 1)
                evidence = manager.last_evidence
                self.assertTrue(evidence['outcome_uncertain'])
                self.assertFalse(evidence['renames'][0]['confirmed'])
                self.assertEqual(len(evidence['renames']), 1)
                self.assertEqual(evidence['pp_save_count'], 0)
                self.assertEqual(evidence['target_project_save_count'], 0)

    def test_cli_keeps_select_add_edit_cancel_argument_order(self):
        add = {'op': 'add-output-group', 'parameter': 'HeatStage1Output', 'outcome': 'accept'}
        edit = {'op': 'edit-output-group', 'parameter': 'HeatStage1Output', 'outcome': 'accept', 'name': 'éPump  Ω'}
        cancel = {'op': 'edit-output-group', 'parameter': 'HeatStage2Output', 'outcome': 'cancel'}
        args = build_parser().parse_args(['thermostat', 'settings', 'preview', NETWORK+'/p/20',
            '--host', 'unused.invalid', '--exclusive-project', '--spec-dir', str(self.directory),
            '--output-group', 'HeatStage1Output=4', '--output-operation', json.dumps(add),
            '--output-operation', json.dumps(edit), '--output-operation', json.dumps(cancel)])
        factory = Mock(return_value=nullcontext(object()))
        with patch('cbus_toolkit.thermostat_templates_cli.NativeThermostatSettings') as cls:
            cls.return_value.plan.return_value.as_dict.return_value = {'literal': 'preview'}
            result, status = run(args, factory)
        self.assertEqual((status, result['literal']), (0, 'preview'))
        kwargs = cls.return_value.plan.call_args.kwargs
        self.assertIsNone(kwargs['output_selections'])
        self.assertEqual(kwargs['output_operations'], [
            {'op': 'select-output-group', 'parameter': 'HeatStage1Output', 'address': '4'}, add, edit, cancel])


if __name__ == '__main__':
    unittest.main()
