"""Native ordered Language Add and static-grid transaction fault boundaries."""
from copy import deepcopy
from contextlib import nullcontext, redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from xml.sax.saxutils import escape
import re
import unittest
from unittest.mock import patch

from cbus_toolkit import cli
from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_parent_metadata import (
    NativeEdltParentError, NativeEdltParentTransaction,
    _complete_application_cache, _snapshot, plan_native_parent_metadata,
)
from cbus_toolkit.edlt_parent_transaction import EdltParentTransaction, normalize_operations
from tests.test_edlt_parent_cache_panels import fixture
from tests.test_edlt_parent_metadata import MetadataClient, NativeSession, FakeProgrammer, oid, response

UNIT = '//TEST/254/p/20'


class LanguageClient(MetadataClient):
    def __init__(self, spec):
        super().__init__(spec)
        self.collection = oid(700)
        self.languages = [dict(id=0, value='8', oid=oid(701)),
                          dict(id=1, value='custom English', oid=oid(702)),
                          dict(id=8, value='custom NZ', oid=oid(703))]
        self.saved_languages, self.saved_collection = deepcopy(self.languages), self.collection
        self.failure_language = None
        self.forged_oid = None
        self.collection_at_end = False
        self.saved_collection_at_end = False

    def xml(self):
        languages = '' if self.collection is None else (
            '<Languages><OID>' + self.collection + '</OID>' + ''.join(
                '<Language><OID>' + r['oid'] + '</OID><ID>' + str(r['id'])
                + '</ID><TagValue>' + escape(r['value']) + '</TagValue></Language>'
                for r in self.languages) + '</Languages>')
        text = super().xml().replace('<Network>', '<Network><OID>' + oid(254) + '</OID>')
        return (text.replace('</Network>', languages + '</Network>') if self.collection_at_end
                else text.replace('<OID>' + oid(254) + '</OID>', '<OID>' + oid(254) + '</OID>' + languages))

    def command(self, command):
        if command.startswith(('DBADD !', 'DBSET !')) or command.startswith('DBDELETE !') and any(
                r['oid'] == command[10:] for r in self.languages) or command.startswith('DBGET !') and (
                    command[7:].split('/')[0] == self.collection or any(
                    r['oid'] == command[7:].split('/')[0] for r in self.languages)):
            self.commands.append(command)
            if self.failure_language is not None:
                outcome = self.failure_language(command)
                if isinstance(outcome, BaseException): raise outcome
                if outcome is not None: return outcome
            if command == 'DBADD !' + oid(254) + ' Languages':
                self.collection = self.forged_oid or self._new_oid()
                self.collection_at_end = True
                return response(301, 'OID=' + self.collection)
            if command == 'DBADD !' + oid(254) + '/Languages Language':
                identity = self.forged_oid or self._new_oid()
                self.languages.append(dict(id=0, value='', oid=identity))
                return response(301, 'OID=' + identity)
            match = re.fullmatch(r'DBSET !([^/]+)/([^ ]+) (.*)', command)
            if match:
                identity, field, value = match.groups()
                r = next(r for r in self.languages if r['oid'] == identity)
                r['id' if field == 'ID' else 'value'] = int(value) if field == 'ID' else value
                return response()
            if command.startswith('DBDELETE !'):
                self.languages = [r for r in self.languages if r['oid'] != command[10:]]
                return response()
            match = re.fullmatch(r'DBGET !([^/]+)/([^ ]+)', command)
            if match:
                identity, field = match.groups()
                value = identity if field == 'OID' else next(r for r in self.languages if r['oid'] == identity)[
                    'id' if field == 'ID' else 'value']
                return response(342, command[6:] + '=' + str(value))
            raise AssertionError(command)
        outcome = super().command(command)
        if command == 'PROJECT SAVE TEST':
            self.saved_languages, self.saved_collection = deepcopy(self.languages), self.collection
            self.saved_collection_at_end = self.collection_at_end
        if command == 'PROJECT LOAD TEST':
            self.languages, self.collection = deepcopy(self.saved_languages), self.saved_collection
            self.collection_at_end = self.saved_collection_at_end
        return outcome


def language(selected, *, cancel=False):
    return dict(op='add-language-dialog', selected_ids=selected, cancel=cancel,
                preferences='registered-defaults')


def grid(index, text):
    return dict(op='static-text-dialog', edits=[dict(index=index, text=text)])


class NativeStaticLanguageTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.client = LanguageClient(self.spec)
        self.session = NativeSession(self.spec, self.client)
        self.programmer = FakeProgrammer(self.session)
        self.manager = NativeEdltParentTransaction(self.client, EdltParentTransaction(self.spec),
                                                   programmer=self.programmer)

    def plan(self, *ops):
        return self.manager.plan(UNIT, operations=ops, exclusive_project=True)

    @staticmethod
    def forged_binding():
        return dict(op='parent-language-binding',
                    receipt=dict(rows_after=[], cancelled=True),
                    group_images=[dict(application=56, group=0, known=True,
                                       images=[False] * 4)],
                    level_labels=[dict(group=0, action=1, labels=[])])

    def test_raw_language_binding_rejected_by_public_normalizers_and_native_planner(self):
        for allow_dialogs in (False, True):
            with self.subTest(allow_dialogs=allow_dialogs):
                with self.assertRaisesRegex(EdltError, 'binding is internal'):
                    normalize_operations((self.forged_binding(), grid(0, 'Forged')),
                                         allow_add_dialog=allow_dialogs)
        with self.assertRaisesRegex(EdltError, 'binding is internal'):
            plan_native_parent_metadata(self.client.xml(), UNIT,
                self.manager.editor.snapshot(self.client.values), self.manager.editor,
                (language([1, 8]), self.forged_binding()))
        with self.assertRaisesRegex(NativeEdltParentError, 'binding is internal'):
            self.plan(self.forged_binding(), grid(0, 'Forged'))
        self.assertEqual(self.programmer.calls, [])
        self.assertFalse(any(c.startswith(('DBADD', 'DBSET', 'DBDELETE', 'PROJECT SAVE', 'PP '))
                             for c in self.client.commands))

    def test_serialized_genuine_binding_cannot_be_resubmitted_as_public_operations(self):
        plan = self.plan(language([1, 8, 74]), grid(0, 'French'))
        # JSON removes the internal provenance type. A published plan is a
        # review artifact, not an alternative input format for trusted facts.
        resolved = plan.as_dict()['resolved_operations']
        self.assertEqual(resolved[0]['op'], 'parent-language-binding')
        with self.assertRaisesRegex(EdltError, 'binding is internal'):
            normalize_operations(resolved, allow_add_dialog=True)
        with self.assertRaisesRegex(TypeError, 'binding is immutable'):
            plan.parent_plan.operations[0]['group_images'] = []
        self.manager.apply(plan)
        self.assertEqual(self.client.commands.count('PP SAVE'), 1)

    def test_native_manager_rejects_untrusted_language_binding_before_any_read(self):
        with patch.object(self.client, 'command',
                          side_effect=AssertionError('Invalid input must not read the project')) as command:
            with self.assertRaisesRegex(NativeEdltParentError, 'binding is internal'):
                self.plan(self.forged_binding(), grid(0, 'Forged'))
            command.assert_not_called()
        self.assertEqual(self.programmer.calls, [])

    def test_public_offline_cli_refuses_forged_binding_with_both_metadata_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            values, project, operations, metadata = (root / name for name in
                ('values.json', 'project.xml', 'operations.json', 'metadata.json'))
            values.write_text(json.dumps(self.manager.editor.snapshot(self.client.values)))
            project.write_text(self.client.xml())
            operations.write_text(json.dumps([self.forged_binding(), grid(0, 'Forged')]))
            metadata.write_text(json.dumps(self.plan(language([1, 8]), grid(0, 'Safe')).cache.as_dict()))
            from cbus_toolkit.edlt_parent_transaction_cli import operations as read_operations
            from types import SimpleNamespace
            with self.assertRaisesRegex(EdltError, 'binding is internal'):
                read_operations(SimpleNamespace(operations=operations))
            for source in (['--project-xml', project, '--unit', UNIT],
                           ['--metadata', metadata]):
                with self.subTest(source=source[0]):
                    stdout, stderr = io.StringIO(), io.StringIO()
                    with redirect_stdout(stdout), redirect_stderr(stderr), patch.object(
                            cli, '_edlt_parent_transaction', return_value=self.manager.editor), patch(
                            'cbus_toolkit.cgate.CGateClient',
                            side_effect=AssertionError('Offline rejection must not connect')):
                        status = cli.main(list(map(str, ['edlt', 'parent-transaction-plan', values,
                                                       *source, '--operations', operations])))
                    self.assertEqual(status, 1, stdout.getvalue() + stderr.getvalue())
                    self.assertIn('binding is internal', stdout.getvalue() + stderr.getvalue())

    def test_public_database_cli_rejects_forged_binding_before_metadata_or_pp_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            operations = Path(directory) / 'operations.json'
            operations.write_text(json.dumps([self.forged_binding(), grid(0, 'Forged')]))
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr), patch.object(
                    cli, '_edlt_parent_transaction', return_value=self.manager.editor), patch(
                    'cbus_toolkit.cgate.CGateClient', return_value=nullcontext(self.client)), patch(
                    'cbus_toolkit.edlt_parent_metadata.Programmer', return_value=self.programmer):
                status = cli.main(list(map(str, ['cgate', 'unit', '--lock-address', '//TEST/254',
                    '--source', '/db' + UNIT, 'edlt-parent-transaction', '--auto-metadata',
                    '--exclusive-project', '--backup-project', 'BACKUP', '--operations', operations])))
            self.assertEqual(status, 1, stdout.getvalue() + stderr.getvalue())
            self.assertIn('binding is internal', stdout.getvalue() + stderr.getvalue())
            self.assertEqual(self.programmer.calls, [])
            self.assertFalse(any(c.startswith(('DBADD', 'DBSET', 'DBDELETE', 'PP ', 'PROJECT SAVE',
                                               'PROJECT COPY', 'PROJECT CLOSE', 'PROJECT LOAD'))
                                 for c in self.client.commands))

    def test_complete_cache_empty_history_keeps_strict_native_image_admission(self):
        self.client.applications[56]['groups'][0] = dict(oid=oid(800), tag='Group', levels=(), tags=[
            dict(language=8, variant=0, type='TEXT', value='NZ text')])
        requirements = {(56, 0): dict(facts=dict(dynamic_images_if_present=[dict(reason='lighting')]))}
        snapshot = _snapshot(self.client.xml(), UNIT, self.manager.editor)
        cache = _complete_application_cache(snapshot, {56}, requirements)
        self.assertTrue(cache.lifecycle.find(56, 0).dynamic_images_known)
        self.assertEqual(cache.lifecycle.find(56, 0).dynamic_images, (False,) * 4)
        self.client.applications[56]['groups'][0]['tags'][0]['type'] = 'FONT'
        snapshot = _snapshot(self.client.xml(), UNIT, self.manager.editor)
        with self.assertRaisesRegex(ValueError, 'not derivable.*DLTP images'):
            _complete_application_cache(snapshot, {56}, requirements)

    def test_repeated_dialog_equivalent_explicit_preference_representations(self):
        explicit=[1,-1,-1,-1,-1,-1,-1,-1]
        for first, second in [('registered-defaults',explicit),(explicit,'registered-defaults')]:
            with self.subTest(first=first):
                one=dict(op='add-language-dialog',selected_ids=[1,8],preferences=first)
                two=dict(op='add-language-dialog',selected_ids=[1,74],preferences=second)
                history=self.plan(one,two).as_dict()['language_dialog_history']
                self.assertEqual(history['final_default'],1)
                self.assertEqual([r['id'] for r in history['final_rows']],[0,1,74])


    def test_real_id_aliases_duplicates_custom_names_and_oid_keep_no_setter(self):
        self.client.languages[1]['id']='+001'
        self.client.languages.extend([dict(id='0001',value='second English',oid=oid(704)),
                                      dict(id='-0001',value='unknown',oid=oid(705))])
        plan=self.plan(language([1,8,74]),grid(3,'French'))
        self.manager.apply(plan)
        self.assertEqual([(r['id'],r['value'],r['oid']) for r in self.client.languages[:-1]],
                         [(0,'8',oid(701)),('+001','custom English',oid(702)),
                          (8,'custom NZ',oid(703)),('0001','second English',oid(704))])
        self.assertEqual(sum(c=='DBDELETE !'+oid(705) for c in self.client.commands),1)
        setters=[c for c in self.client.commands if c.startswith('DBSET !')]
        self.assertFalse(any(c.startswith('DBSET !'+identity+'/') for c in setters for identity in (oid(702),oid(703),oid(704))))
        self.assertEqual(len(setters),4)  # newFrench ID/name, marker ID/default


    def test_language_default_repair_static_grid_and_parent_one_save_preserve_names_identities(self):
        plan = self.plan(language([74, 1]), grid(3, 'French display'))
        history = plan.as_dict()['language_dialog_history']
        self.assertEqual(history['final_default'], 74)
        self.assertEqual(history['steps'][0]['out_result'], '1')
        result = self.manager.apply(plan, backup_project='BACKUP').as_dict()
        self.assertTrue(result['saved'])
        self.assertTrue(result['language_rows_verified_before_pp'])
        self.assertEqual([(r['id'], r['value']) for r in self.client.languages],
                         [(0, '74'), (1, 'custom English'), (74, 'French')])
        self.assertEqual([r['oid'] for r in self.client.languages[:2]], [oid(701), oid(702)])
        self.assertEqual(self.client.commands.count('PP SAVE'), 1)
        self.assertEqual(self.client.commands.count('PROJECT SAVE TEST'), 2)  # backup baseline + final target
        self.assertEqual(self.client.values['StaticTextString3'].split()[0:7], ['70', '114', '101', '110', '99', '104', '32'])

    def test_cancellation_is_read_only_for_language_collection(self):
        before = deepcopy(self.client.languages)
        plan = self.plan(language([], cancel=True), grid(2, 'Static'))
        self.manager.apply(plan)
        self.assertEqual(self.client.languages, before)
        self.assertFalse(any(c.startswith(('DBADD !', 'DBSET !', 'DBDELETE !')) for c in self.client.commands))

    def test_repeated_language_dialogs_create_then_remove_same_new_row_without_replay(self):
        plan = self.plan(language([1, 8, 74]), language([1, 8, 80]), grid(4, 'German'))
        self.manager.apply(plan)
        self.assertEqual([r['id'] for r in self.client.languages], [0, 1, 8, 80])
        self.assertEqual(sum(c.startswith('DBADD !') for c in self.client.commands), 2)
        self.assertEqual(sum(c.startswith('DBDELETE !') for c in self.client.commands), 1)
        with self.assertRaises(NativeEdltParentError): self.manager.apply(plan)
        self.assertEqual(sum(c.startswith('DBADD !') for c in self.client.commands), 2)

    def test_absent_collection_created_and_zero_marker_repaired_by_first_selected(self):
        self.client.collection = None
        self.client.languages = []
        plan = self.plan(language([1, 202]), grid(0, 'Chinese'))
        self.manager.apply(plan)
        self.assertEqual([r['id'] for r in self.client.languages], [1, 202, 0])
        self.assertTrue(self.client.collection)
        self.assertEqual(sum(c.startswith('DBADD !') for c in self.client.commands), 4)
        other = LanguageClient(self.spec)
        other.languages[0]['value'] = '0'
        manager = NativeEdltParentTransaction(other, EdltParentTransaction(self.spec),
            programmer=FakeProgrammer(NativeSession(self.spec, other)))
        plan = manager.plan(UNIT, operations=(language([8, 1]), grid(0, 'NZ')), exclusive_project=True)
        manager.apply(plan)
        self.assertEqual(other.languages[0]['value'], '8')

    def test_observed_foreign_oid_rejected_before_id_tagvalue_or_inverse_delete(self):
        self.client.forged_oid = oid(999)
        plan = self.plan(language([1, 8, 74]), grid(2, 'New'))
        with self.assertRaises(NativeEdltParentError) as caught: self.manager.apply(plan)
        self.assertTrue(caught.exception.result.as_dict()['rollback_verified'])
        self.assertFalse(any(c.startswith(('DBSET !', 'DBDELETE !')) for c in self.client.commands))
        self.assertEqual(self.programmer.calls, [])

    def test_interrupted_language_set_reloads_source_without_deleting_old_or_saving_unknown_mutation(self):
        before = deepcopy(self.client.languages)
        self.client.failure_language = lambda c: RuntimeError('lost receipt') if c.startswith('DBSET !') else None
        plan = self.plan(language([1, 74]), grid(2, 'New'))
        with self.assertRaises(NativeEdltParentError) as caught: self.manager.apply(plan)
        evidence = caught.exception.result.as_dict()
        self.assertTrue(evidence['rollback_verified'])
        self.assertEqual(self.client.languages, before)
        self.assertEqual(self.client.commands.count('PROJECT SAVE TEST'), 1)
        self.assertEqual(self.programmer.calls, [])
        self.assertEqual(sum(c.startswith('DBSET !') for c in self.client.commands), 1)

    def test_interrupted_pp_save_never_replays_language_or_restores_after_attempt(self):
        self.session.save_error = RuntimeError('lost PP receipt')
        plan = self.plan(language([1, 74]), grid(2, 'New'))
        with self.assertRaises(NativeEdltParentError) as caught: self.manager.apply(plan)
        evidence = caught.exception.result.as_dict()
        self.assertTrue(evidence['pp_save_outcome_uncertain'])
        self.assertFalse(evidence['rollback_attempted'])
        self.assertEqual(self.client.commands.count('PP SAVE'), 1)
        self.assertNotIn('PROJECT CLOSE TEST', self.client.commands)
        count = len(self.client.commands)
        with self.assertRaises(NativeEdltParentError): self.manager.apply(plan)
        self.assertEqual(len(self.client.commands), count)

    def test_new_default_image_facts_are_consumed_only_after_language_binding(self):
        self.client.applications[56]['groups'][0] = dict(oid=oid(800), tag='Group', levels=(), tags=[
            dict(language=8, variant=0, type='TEXT', value='NZ text'),
            dict(language=74, variant=0, type='FONT', value='unresolved image')])
        lighting = dict(op='lighting', page=1, position=1, group=0, mode='off-on',
                        label_type='dynamic-text', label_index=0)
        # The same admitted control before the language selection sees TEXT.
        self.plan(lighting, language([74, 1]))
        # After selection it sees the unresolved FONT source and refuses
        # locally; it cannot borrow the former language's TEXT evidence.
        with self.assertRaisesRegex(NativeEdltParentError, 'image|dynamic'):
            self.plan(language([74, 1]), lighting)
        self.assertFalse(any(c.startswith(('PROJECT SAVE', 'DBADD', 'DBSET', 'PP SAVE'))
                             for c in self.client.commands))

    def test_language_binding_can_resolve_initially_unused_font_before_new_widget(self):
        self.client.applications[56]['groups'][0] = dict(oid=oid(800), tag='Group', levels=(), tags=[
            dict(language=8, variant=0, type='FONT', value='unresolved image'),
            dict(language=74, variant=0, type='TEXT', value='French text')])
        lighting = dict(op='lighting', page=1, position=1, group=0, mode='off-on',
                        label_type='dynamic-text', label_index=0)
        with self.assertRaisesRegex(NativeEdltParentError, 'image|dynamic'):
            self.plan(lighting, language([74, 1]))
        plan = self.plan(language([74, 1]), lighting)
        # The initial parent still retains an unknown image fact. Only the
        # earlier real dialog supplies TEXT for the later new widget.
        self.assertFalse(plan.parent_plan.metadata.find(56, 0).dynamic_images_known)
        self.manager.apply(plan)
        self.assertEqual(self.client.commands.count('PP SAVE'), 1)

    def test_later_language_binding_cannot_resolve_initial_retained_dynamic_widget(self):
        self.client.applications[56]['groups'][0] = dict(oid=oid(800), tag='Group', levels=(), tags=[
            dict(language=8, variant=0, type='FONT', value='unresolved image'),
            dict(language=74, variant=0, type='TEXT', value='French text')])
        self.client.values.update(Widget1WidgetType='2', Widget1WidgetByteValue1='16',
                                  Widget1WidgetByteValue6='0', Widget1WidgetByteValue13='0')
        with self.assertRaisesRegex(NativeEdltParentError, 'image|dynamic'):
            self.plan(language([74, 1]), grid(0, 'French'))
        self.assertFalse(any(c.startswith(('PROJECT SAVE', 'DBADD', 'DBSET', 'DBDELETE', 'PP '))
                             for c in self.client.commands))


if __name__ == '__main__': unittest.main()
