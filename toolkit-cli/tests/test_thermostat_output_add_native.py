"""Independent exact wire and failure-boundary tests; no endpoint is used.

The scripted client drives the real NativeDatabase adapter and the owning
settings graph materializer. It does not simulate original C-Gate acceptance.
Public CLI parser/dispatch tests stop before any real connection.
"""
from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from cbus_toolkit.cli import build_parser
from cbus_toolkit.thermostat_remote_references import (ProjectGraphSnapshot,
    RemoteApplication, RemoteCreation)
from cbus_toolkit.thermostat_settings import NativeThermostatSettings, _quoted_group_tag
from cbus_toolkit.thermostat_templates import ThermostatTemplateError
from cbus_toolkit.thermostat_templates_cli import run
from cbus_toolkit.unitspec import UnitSpecStore

APP_OID = '10000000-0000-4000-8000-000000000001'
GROUP_OID = '20000000-0000-4000-8000-000000000002'
OTHER_OID = '30000000-0000-4000-8000-000000000003'
NETWORK = '//ADD/254'


def reply(code, *lines):
    return SimpleNamespace(code=code, lines=list(lines), final=lines[-1] if lines else '')


def identity(path, oid):
    return reply(342, '342 ' + path + '/OID=' + oid)


class ScriptedClient:
    def __init__(self, test, script):
        self.test, self.script, self.commands = test, list(script), []

    def command(self, text):
        self.commands.append(text)
        self.test.assertTrue(self.script, 'Unexpected command: ' + text)
        expected, result = self.script.pop(0)
        self.test.assertEqual(text, expected)
        if isinstance(result, BaseException):
            raise result
        return result


class OutputAddNativeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.store = UnitSpecStore(self.directory)

    def manager(self, script):
        client = ScriptedClient(self, script)
        manager = NativeThermostatSettings(client, self.store)
        manager._start('independent-output-add-materialization')
        return manager, client

    def plan(self, application=56, *, name='Added group', operations=None, existing_application=True):
        applications = (RemoteApplication(application, APP_OID, 'Existing application', (), ''),) if existing_application else ()
        graph = ProjectGraphSnapshot('ADD', 254, 20, NETWORK+'/p/20', (), applications,
                                     (APP_OID,) if existing_application else (), '', '')
        row = RemoteCreation('Group', application, 4, name, 'output_add:1:HeatStage1Output', True)
        return SimpleNamespace(network=NETWORK,
            remote=SimpleNamespace(graph=graph, graph_operations=(row,) if operations is None else operations))

    def prefix(self, application=56, oid=GROUP_OID):
        parent = NETWORK + '/' + str(application)
        return [('DBGET '+parent+'/OID', identity(parent, APP_OID)),
                ('DBADD !'+APP_OID+' Group', reply(301, '301 OID='+oid)),
                ('DBGET !'+oid+'/OID', identity('!'+oid, oid))]

    def fail(self, manager, plan):
        with self.assertRaises((ValueError, RuntimeError, TimeoutError)) as caught:
            manager._create_references(plan)
        with self.assertRaises(Exception):
            manager._fail(caught.exception)
        return caught.exception

    def test_source_serializer_literal_unicode_quotes_and_conditional_spaces(self):
        cases = [
            ('Group 4', '"Group 4"'),
            ('A B C', '"A B C"'),
            ('A  B C', r'"A\ \ B\ C"'),
            ('éPump  Ω', r'"éPump\ \ Ω"'),
            ('\u00a0', '"\u00a0"'),
            ('A\u00a0B', '"A\u00a0B"'),
            ('# "X"\\Y', r'"# \"X\"\\Y"'),
            ('😀' * 16, '"' + '😀' * 16 + '"'),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(_quoted_group_tag(raw), expected)

    def test_protocol_controls_refuse_before_parent_read_or_creation(self):
        for control in ('\x00', '\t', '\r', '\n', '\x1f', '\x7f'):
            with self.subTest(control=repr(control)):
                manager, client = self.manager([])
                with self.assertRaisesRegex(ValueError, 'control characters'):
                    manager._create_references(self.plan(name='A'+control+'B'))
                self.assertEqual(client.commands, [])
                self.assertFalse(manager.last_evidence['graph_mutation_attempted'])

    def test_group_creation_literal_order_for_lighting_and_enable_application(self):
        for application in (56, 203):
            with self.subTest(application=application):
                script = self.prefix(application) + [
                    ('DBSET !'+GROUP_OID+'/Address 4', reply(200, '200 OK.')),
                    ('DBSET !'+GROUP_OID+'/TagName '+r'"éPump\ \ Ω"', reply(200, '200 OK.'))]
                manager, client = self.manager(script)
                self.assertEqual(manager._create_references(self.plan(application, name='éPump  Ω')),
                                 {('Group', application, 4): GROUP_OID})
                self.assertFalse(client.script)
                evidence = manager.last_evidence
                self.assertFalse(evidence['graph_mutation_outcome_uncertain'])
                for journal in ('objects', 'graph_operations'):
                    row = evidence[journal][0]
                    self.assertTrue(all(row[k] for k in ('created', 'address_confirmed', 'tag_confirmed', 'confirmed')))
                    self.assertEqual(row['oid'], GROUP_OID)
                self.assertEqual(evidence['pp_save_count'], 0)
                self.assertEqual(evidence['target_project_save_count'], 0)

    def test_stale_parent_or_wrong_pending_identity_stops_at_read_boundary(self):
        parent = NETWORK+'/56'
        manager, client = self.manager([('DBGET '+parent+'/OID', identity(parent, OTHER_OID))])
        with self.assertRaisesRegex(ThermostatTemplateError, 'owning application identity changed'):
            manager._create_references(self.plan())
        self.assertEqual(len(client.commands), 1)
        self.assertFalse(manager.last_evidence['graph_mutation_attempted'])
        for response in (identity('!'+GROUP_OID, OTHER_OID), reply(200, '200 OK.'),
                         reply(342, '342 !'+GROUP_OID+'/OID='+GROUP_OID, '342 duplicate')):
            with self.subTest(response=response.lines):
                script = self.prefix()
                script[-1] = (script[-1][0], response)
                manager, client = self.manager(script)
                self.fail(manager, self.plan())
                self.assertEqual(len(client.commands), 3)
                self.assertTrue(manager.last_evidence['graph_mutation_outcome_uncertain'])
                self.assertEqual(manager.last_evidence['state'], 'uncertain')
                self.assertNotIn('field_attempted', manager.last_evidence['objects'][0])

    def test_malformed_or_preexisting_301_never_reaches_field_writes(self):
        responses = [reply(200, '200 OK.'), reply(301, '301 OID='+GROUP_OID, '301 OID='+OTHER_OID),
                     reply(301, '301-OID='+GROUP_OID), reply(301, '301 OID=not-an-oid'),
                     reply(301, '301 OID='+APP_OID)]
        for response in responses:
            with self.subTest(response=response.lines):
                script = self.prefix()[:2]
                script[-1] = (script[-1][0], response)
                manager, client = self.manager(script)
                self.fail(manager, self.plan())
                self.assertEqual(len(client.commands), 2)
                self.assertTrue(manager.last_evidence['outcome_uncertain'])
                self.assertFalse(manager.last_evidence['objects'][0]['confirmed'])
                self.assertFalse(any(command.startswith('DBSET') for command in client.commands))

    def test_duplicate_issued_oid_after_first_add_does_not_modify_first_group(self):
        rows = (RemoteCreation('Group', 56, 4, 'First', 'output_add:1:HeatStage1Output', True),
                RemoteCreation('Group', 56, 5, 'Second', 'output_add:2:HeatStage2Output', True))
        script = self.prefix() + [
            ('DBSET !'+GROUP_OID+'/Address 4', reply(200, '200 OK.')),
            ('DBSET !'+GROUP_OID+'/TagName "First"', reply(200, '200 OK.')),
            *self.prefix()[:2]]
        manager, client = self.manager(script)
        self.fail(manager, self.plan(operations=rows))
        self.assertFalse(client.script)
        self.assertEqual(sum(command.startswith('DBSET') for command in client.commands), 2)
        first, second = manager.last_evidence['objects']
        self.assertTrue(first['confirmed'])
        self.assertFalse(second['confirmed'])
        self.assertTrue(manager.last_evidence['outcome_uncertain'])

    def test_lost_create_address_or_tag_reply_has_no_replay_or_later_writes(self):
        complete = self.prefix() + [
            ('DBSET !'+GROUP_OID+'/Address 4', reply(200, '200 OK.')),
            ('DBSET !'+GROUP_OID+'/TagName "Added group"', reply(200, '200 OK.'))]
        for failed_index in (1, 3, 4):
            with self.subTest(command=complete[failed_index][0]):
                script = complete[:failed_index] + [(complete[failed_index][0], TimeoutError('lost reply'))]
                manager, client = self.manager(script)
                self.fail(manager, self.plan())
                self.assertEqual(client.commands, [command for command, _response in script])
                evidence = manager.last_evidence
                self.assertTrue(evidence['outcome_uncertain'])
                self.assertFalse(evidence['objects'][0]['confirmed'])
                self.assertEqual(evidence['pp_save_count'], 0)
                self.assertEqual(evidence['target_project_save_count'], 0)
                self.assertNotIn('tag_confirmed', evidence['objects'][0])
                if failed_index == 4:
                    self.assertTrue(evidence['objects'][0]['address_confirmed'])

    def test_nonterminal_field_success_is_not_accepted(self):
        for response in (reply(200, '200 OK.', '200 duplicate'), reply(301, '301 OID='+OTHER_OID)):
            with self.subTest(response=response.lines):
                script = self.prefix() + [('DBSET !'+GROUP_OID+'/Address 4', response)]
                manager, client = self.manager(script)
                self.fail(manager, self.plan())
                self.assertFalse(client.script)
                self.assertNotIn('address_confirmed', manager.last_evidence['objects'][0])
                self.assertTrue(manager.last_evidence['outcome_uncertain'])

    def test_existing_creation_route_and_new_application_oid_binding_remain_distinct(self):
        rows = (RemoteCreation('Application', 203, 203, 'Enable Control', 'ordinary-load'),
                RemoteCreation('Group', 203, 4, 'Enable Network Variable 4', 'output_add:1:HeatStage1Output', True))
        script = [('DBADDSAFE '+NETWORK+' Application 203 Enable Control', reply(301, '301 OID='+APP_OID)),
                  ('DBGET !'+APP_OID+'/OID', identity('!'+APP_OID, APP_OID)),
                  *self.prefix(203),
                  ('DBSET !'+GROUP_OID+'/Address 4', reply(200, '200 OK.')),
                  ('DBSET !'+GROUP_OID+'/TagName "Enable Network Variable 4"', reply(200, '200 OK.'))]
        manager, client = self.manager(script)
        created = manager._create_references(self.plan(203, operations=rows, existing_application=False))
        self.assertEqual(created, {('Application', 203, 203): APP_OID, ('Group', 203, 4): GROUP_OID})
        self.assertFalse(client.script)
        self.assertNotIn('output_add', manager.last_evidence['objects'][0])
        self.assertTrue(manager.last_evidence['objects'][1]['output_add'])

    def cli_args(self, *extra):
        return build_parser().parse_args(['thermostat', 'settings', 'preview', NETWORK+'/p/20',
            '--host', 'unused.invalid', '--exclusive-project', '--spec-dir', str(self.directory), *extra])

    def test_public_cli_interleaves_selection_and_add_in_argument_order(self):
        operation = {'op': 'add-output-group', 'parameter': 'CoolStage1Output', 'outcome': 'accept', 'name': 'éPump  Ω'}
        cancel = {'op': 'add-output-group', 'parameter': 'CoolStage2Output', 'outcome': 'cancel'}
        args = self.cli_args('--output-group', 'CoolFanLowOutput=255',
            '--output-operation', json.dumps(operation), '--output-group', 'CoolFanMediumOutput=4',
            '--output-operation', json.dumps(cancel))
        client = object()
        factory = Mock(return_value=nullcontext(client))
        plan = Mock()
        plan.as_dict.return_value = {'literal': 'preview'}
        with patch('cbus_toolkit.thermostat_templates_cli.NativeThermostatSettings') as cls:
            cls.return_value.plan.return_value = plan
            result, status = run(args, factory)
        self.assertEqual(status, 0)
        self.assertEqual(result['literal'], 'preview')
        kwargs = cls.return_value.plan.call_args.kwargs
        self.assertIsNone(kwargs['output_selections'])
        self.assertEqual(kwargs['output_operations'], [
            {'op': 'select-output-group', 'parameter': 'CoolFanLowOutput', 'address': '255'}, operation,
            {'op': 'select-output-group', 'parameter': 'CoolFanMediumOutput', 'address': '4'}, cancel])
        factory.assert_called_once_with('unused.invalid', 20023, timeout=30.0)

    def test_public_cli_duplicate_json_keys_and_constants_refuse_before_connection(self):
        bad = ['{"op":"add-output-group","op":"select-output-group"}',
               '{"op":"add-output-group","nested":{"a":1,"a":2}}',
               '{"op":"add-output-group","name":NaN}', '[]', 'null', '{']
        for text in bad:
            with self.subTest(text=text):
                args = self.cli_args('--output-operation', text)
                factory = Mock(side_effect=AssertionError('must not connect'))
                with self.assertRaises(ValueError):
                    run(args, factory)
                factory.assert_not_called()


if __name__ == '__main__':
    unittest.main()
